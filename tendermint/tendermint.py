# https://arxiv.org/pdf/1807.04938
# https://timroughgarden.github.io/fob21/l/l7.pdf
import time
import zlib
import string
import random
from collections import Counter, defaultdict
import message_queue


NIL = None



def get_value():
    """
    Returns a valid block (which they call a 'value' in the paper)

    From the paper:
    "In the initial round of each height, the proposer is free to chose the value
    to suggest.  In the Algorithm 1, a correct process obtains a value to propose
    using an external function getValue() that returns a valid value to propose."
    """
    # Our "blocks" will be random strings of 4 characters
    return "".join(random.choice(string.ascii_letters) for _ in range(4))


class TendermintNode:
    def __init__(self, node_id, num_nodes, message_queue, scheduler, verbose=False):
        # Using variable names from https://arxiv.org/pdf/1807.04938, page 7
        # current height, or consensus instance we are currently executing
        self.h = 0
        # current round number
        self.round = 0
        # {propose, prevote, precommit}
        self.step = "propose"
        # our blockchain, a mapping from h to block (or 'value' in the paper terminology)
        self.decision = {}
        # value = block
        self.locked_value = NIL
        self.locked_round = -1
        self.valid_value = NIL
        self.valid_round = -1

        ##########
        self.node_id = node_id
        self.num_nodes = num_nodes
        # From the paper: "for simplicity we present the algorithm for the case n = 3f + 1"
        self.f = (num_nodes - 1) / 3
        assert self.f == int(self.f), "(num_nodes-1) must be divisble by 3!"
        self.message_queue = message_queue
        self.scheduler = scheduler

        # Paper description involves storing all messages sent and received in a message log
        # We'll store the information we need in these dicts
        self.proposals = {}
        # Nested dict store all our votes: round -> node_id -> block_hash
        self.prevotes = defaultdict(dict)
        self.precommits = defaultdict(dict)

        # node_ids of other nodes, we'll use this for broadcasting
        self.peers = []
        self.verbose = verbose

    def add_peer(self, peer_id):
        """
        peer_id is an int from 0 to num_nodes-1
        """
        assert isinstance(peer_id, int)
        self.peers.append(peer_id)

    def broadcast(self, msg):
        """
        all to all communication
        """
        for p in self.peers:
            # copying messages so we can pop the msg_type
            self.message_queue.send_message(p, dict(msg))
        # Algorithm also calls for storing our own messages in the message log
        # We can accomplish this by processing our own message
        self.process_message(msg)

    def schedule(self, msg, scheduled_time):
        self.scheduler.schedule_message(self.node_id, msg, scheduled_time)

    def process_message(self, msg):
        if self.verbose:
            print(self.node_id, "process_message received:", msg)
        handler_map = {
            "PROPOSAL": self.handle_proposal,
            "PREVOTE": self.handle_prevote,
            "PRECOMMIT": self.handle_precommit,
            "PROPOSAL_TIMEOUT": self.on_timeout_proposal,
            "PREVOTE_TIMEOUT": self.on_timeout_prevote,
            "PRECOMMIT_TIMEOUT": self.on_timeout_precommit,
        }
        msg_type = msg.pop("msg_type")
        handler_map[msg_type](**msg)

    def proposer(self, h, round):
        """
        Returns the node_id of the proposer for a given block height and round

        From the paper:
        "We assume that the proposer selection function is weighted round-
        robin, where processes are rotated proportional to their voting power"

        We'll use unweighted round robin for simplicity
        """
        return round % self.num_nodes

    def valid(self, v):
        """
        Returns whether or not a block is valid.  'get_value' returns a 4 
        character string, so we'll treat any 4 character string as valid
        """
        return isinstance(v, str) and len(v)==4

    def id_(self, v):
        """
        Returns the id of the block

        From the paper:
        "we are explicit about sending a value (block of transactions) and a small,
        constant size value id (a unique value identifier, normally a hash of the
        value)... The PROPOSAL message is the only one carrying the value; PREVOTE
        and PRECOMMIT messages carry the value id."
        """
        return zlib.crc32(v.encode())

    def _tally_votes(self, votes_dict):
        """
        Input is a dictionary of votes for a given round, 
        key is the node_id, value is their vote in id_(v) format
        """
        votes = Counter(votes_dict.values())
        print("VOTES", votes, "THRESHOLD", 2 * self.f + 1)
        qc = [x for x in votes if votes[x] >= (2 * self.f + 1)]
        if qc:
            # Can only ever have one QC, so return [0]
            return True, qc[0]
        return False, None

    def broadcast_proposal(self, h, round, proposal, valid_round):
        msg = {
            "msg_type": "PROPOSAL",
            "sender": self.node_id,
            "h": h,
            "round": round,
            "proposal": proposal,
            "valid_round": valid_round,
        }
        self.broadcast(msg)

    def broadcast_prevote(self, h, round, id_v):
        msg = {
            "msg_type": "PREVOTE",
            "sender": self.node_id,
            "h": h,
            "round": round,
            "id_v": id_v,
        }
        self.broadcast(msg)

    def broadcast_precommit(self, h, round, id_v):
        msg = {
            "msg_type": "PRECOMMIT",
            "sender": self.node_id,
            "h": h,
            "round": round,
            "id_v": id_v,
        }
        self.broadcast(msg)

    def schedule_ontimeout_proposal(self, h, round):
        msg = {
            "msg_type": "PROPOSAL_TIMEOUT",
            "height": h,
            "round": round,
        }
        self.schedule(msg, time.time() + 5)

    def schedule_ontimeout_prevote(self, h, round):
        msg = {
            "msg_type": "PREVOTE_TIMEOUT",
            "height": h,
            "round": round,
        }
        self.schedule(msg, time.time() + 5)

    def schedule_ontimeout_precommit(self, h, round):
        msg = {
            "msg_type": "PRECOMMIT_TIMEOUT",
            "height": h,
            "round": round,
        }
        self.schedule(msg, time.time() + 5)

    def start_round(self, round):
        """
        ## lines 11-21
        """
        self.round = round
        self.step = "propose"

        if self.proposer(self.h, self.round) == self.node_id:
            """
            If in the previous round we saw a prevote QC, but NOT a precommit QC,
            we will not have cleared the 'valid_value' from the previous round, 
            so we will reuse that value.  Otherwise we'll propose a new block/value
            """
            if self.valid_value is not NIL:
                proposal = self.valid_value
            else:
                proposal = get_value()
            
            #  In addition to the value proposed, the PROPOSAL message also contains the validRound so other processes are informed about the last round in which the proposer observed validV alue as a possible decision value.
            self.broadcast_proposal(self.h, round, proposal, self.valid_round)
            # At this point we meet the conditions to run lines 22-27, so do that here
            self.broadcast_prevote(self.h, round, self.id_(proposal))
            self.step = "prevote"
        else:
            self.schedule_ontimeout_proposal(self.h, self.round)

    def handle_proposal(self, sender, h, round, proposal, valid_round):
        ## lines 22-27
        assert sender == self.proposer(h, round)

        # Storing it in a message log
        assert (h, round) not in self.proposals, "Shouldn't receive multiple proposals!"
        self.proposals[(h, round)] = {"proposal": proposal, "valid_round": valid_round}

        print("HANDLE PROPOSAL CHECK...")
        if valid_round == -1:
            if self.valid(proposal) and (self.locked_round == -1 or self.locked_value == proposal):
                self.broadcast_prevote(h, round, self.id_(proposal))
            else:
                self.broadcast_prevote(h, round, NIL)
            self.step = "prevote"


    def handle_prevote(self, sender, h, round, id_v):
        ## lines 34-35
        assert sender not in self.prevotes[round], "Shouldn't receive multiple prevotes!"
        self.prevotes[round][sender] = id_v
        num_prevotes = len(self.prevotes[round])
        have_qc, qc_idv = self._tally_votes(self.prevotes[round])
        print("HAVE QC?", have_qc)

        ## lines 28-33

        """
        Is this to handle scenario where we are behind a round?
        If we see proposal for a different round we won't prevote in response
        to the proposal, but if enough people vote we can be overruled?
        """
        valid_round = self.proposals[(h, round)]["valid_round"]
        proposal = self.proposals[(h, round)]["proposal"]

        if have_qc and self.step == "propose" and valid_round >= 0 and valid_round < self.round:
            if self.valid(proposal) and (
                self.locked_round <= valid_round or self.locked_value == proposal
            ):
                self.broadcast_prevote(h, round, self.id_(proposal))
            else:
                self.broadcast_prevote(h, round, NIL)
            self.step = "prevote"

        ## lines 34-35 
        if self.step == "prevote":
            # Upon 2f+1
            # By checking for exact count we'll only do it once!
            if num_prevotes == (2 * self.f + 1):
                self.schedule_ontimeout_prevote(h, round)


        ## lines 36-43
        if have_qc and self.step in {"prevote", "precommit"}:
            proposal = self.proposals[(h, round)]["proposal"]
            if self.valid(proposal) and qc_idv == self.id_(proposal):
                if self.step == "prevote":
                    self.locked_value = proposal
                    self.locked_round = round
                    self.broadcast_precommit(h, round, qc_idv)
                    self.step = "precommit"
                self.valid_value = proposal
                self.valid_round = round

        # TODO - think we could broadcast twice?
        ## lines 44-46
        if self.step == "prevote" and have_qc and qc_idv == NIL:
            self.broadcast_precommit(h, round, NIL)
            self.step = "precommit"


    def handle_precommit(self, sender, h, round, id_v):
        """
        ## lines 49-55
        """
        # Can they ever vote more than once in a round?
        # Should we add assertion that they haven't voted yet?
        assert sender not in self.precommits[round], "Shouldn't receive multiple precommits!"
        self.precommits[round][sender] = id_v
        num_precommits = len(self.precommits[round])
        have_qc, qc_idv = self._tally_votes(self.precommits[round])

        # Upon 2f+1 votes
        # Only do it once!
        if num_precommits == (2 * self.f + 1):
            self.schedule_ontimeout_precommit(h, round)

        if have_qc and self.decision.get(h, NIL) == NIL:
            proposal = self.proposals[(h, round)]["proposal"]
            # Make sure it matches what we have for our proposal
            if self.valid(proposal) and qc_idv == self.id_(proposal):
                blocks = [self.decision.get(i) for i in range(h)]
                print("FINALIZED BLOCK!!!!!!!!!", blocks)

                self.decision[h] = proposal
                self.h += 1
                self.locked_round = -1
                self.locked_value = NIL
                self.valid_round = -1
                self.valid_value = NIL
                self.start_round(round+1)



    # TODO - need this!
    # lines 55-59
    # If we start getting votes for future round, we need to start it!
    # upon f + 1 h∗, hp, round, ∗, ∗i with round > roundp do
    #     StartRound(round)

    def on_timeout_proposal(self, height, round):
        """
        ## lines 57-60

        From the paper:
        "A correct process will send PREVOTE message with nil value also in case
        timeoutPropose expired (it is triggered when a correct process starts a
        new round) and a process has not sent PREVOTE message in the current
        round yet."

        If things are going well, this condition will NOT be met, and we won't
        broadcast a nil prevote here
        """
        if height == self.h and round == self.round and self.step == "propose":
            self.broadcast_prevote(height, round, NIL)
            self.step = "prevote"

    def on_timeout_prevote(self, height, round):
        """
        ## lines 61-64
        """
        if height == self.h and round == self.round and self.step == "prevote":
            self.broadcast_precommit(height, round, NIL)
            self.step = "precommit"

    def on_timeout_precommit(self, height, round):
        """
        ## lines 65-67
        """
        if height == self.h and round == self.round:
            self.start_round(round + 1)


if __name__ == "__main__":
    n = 4

    nodes = {}
    message_queue = message_queue.MessageQueue(nodes)

    for i in range(n):
        node = TendermintNode(i, n, message_queue, message_queue)
        nodes[i] = node

    threads = []
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            nodes[i].add_peer(j)

    for i in nodes:
        # Start them off...
        nodes[i].start_round(0)

    message_queue.run()
