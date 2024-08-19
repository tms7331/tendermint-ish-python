import algorithm
import message_queue

"""
SAFETY FAILURE EXAMPLE
Nodes can collude - when it's a byzantine's node to propose, send different
proposals to 1/2 of the nodes (equivocation).  All byzantine nodes vote for those 
same proposals to the same nodes in prevote and precommit voting rounds.
"""


class CollusionTracker:
    """
    Stores which nodes should receive which proposals
    """

    def __init__(self, byzantine_nodes):
        self._votes = {}
        self.byzantine_nodes = byzantine_nodes

    def store_vote(self, node_id, round, id_v):
        """
        When broadcasting proposals, track which block we proposed
        to each node
        """
        if round not in self._votes:
            self._votes[round] = {}
        # What we'll pass around is actually the id(p)...
        self._votes[round][node_id] = id_v

    def get_idv(self, node_id, round, id_v_default):
        try:
            return self._votes[round][node_id]
        except:
            return id_v_default


class TendermintNodeByzantineCollude(algorithm.TendermintNode):
    """
    A tendermint node which sends different information to different nodes
    """

    def __init__(
        self,
        node_id,
        num_nodes,
        round_time,
        mq,
        scheduler,
        collusion_tracker,
        verbose=False,
    ):
        super().__init__(node_id, num_nodes, round_time, mq, scheduler, verbose)
        self.collusion_tracker = collusion_tracker

    def broadcast_proposal(self, h, round, proposal, valid_round):
        """
        So if it's our turn to propose, we'll propose one block to half the nodes
        And generate a new valid block to propose to the other half
        """

        # We'll lie to first half of honest nodes...
        proposal_alt = algorithm.get_value()
        honest_nodes = [
            x for x in self.peers if x not in self.collusion_tracker.byzantine_nodes
        ]
        send_alt = honest_nodes[: len(honest_nodes) // 2]

        for to_node_id in send_alt:
            msg = {
                "msg_type": "PROPOSAL",
                "sender": self.node_id,
                "h": h,
                "round": round,
                "proposal": proposal_alt,
                "valid_round": valid_round,
            }
            self.message_queue.send_message(to_node_id, msg)
            self.collusion_tracker.store_vote(to_node_id, round, self.id_(proposal_alt))

        msg = {
            "msg_type": "PROPOSAL",
            "sender": self.node_id,
            "h": h,
            "round": round,
            "proposal": proposal,
            "valid_round": valid_round,
        }
        for to_node_id in self.peers:
            if to_node_id in send_alt:
                continue
            self.message_queue.send_message(to_node_id, dict(msg))
            self.collusion_tracker.store_vote(to_node_id, round, self.id_(proposal))

        self.process_message(msg)

    def broadcast_prevote(self, h, round, id_v_default):
        for to_node_id in self.peers:
            id_v = self.collusion_tracker.get_idv(to_node_id, round, id_v_default)
            # copying messages so we can pop the msg_type
            msg = {
                "msg_type": "PREVOTE",
                "sender": self.node_id,
                "h": h,
                "round": round,
                "id_v": id_v,
            }
            self.message_queue.send_message(to_node_id, msg)

        msg = {
            "msg_type": "PREVOTE",
            "sender": self.node_id,
            "h": h,
            "round": round,
            "id_v": id_v_default,
        }
        self.process_message(msg)

    def broadcast_precommit(self, h, round, id_v_default):
        for to_node_id in self.peers:
            id_v = self.collusion_tracker.get_idv(to_node_id, round, id_v_default)
            # copying messages so we can pop the msg_type
            msg = {
                "msg_type": "PRECOMMIT",
                "sender": self.node_id,
                "h": h,
                "round": round,
                "id_v": id_v,
            }
            self.message_queue.send_message(to_node_id, msg)

        msg = {
            "msg_type": "PRECOMMIT",
            "sender": self.node_id,
            "h": h,
            "round": round,
            "id_v": id_v_default,
        }
        self.process_message(msg)


n = 4
nodes = {}


byzantine_nodes = {2, 3}
round_time = 1

mq = message_queue.MessageQueue(nodes, round_time)
collusion_tracker = CollusionTracker(byzantine_nodes)

for i in range(n):
    verbose = True if i == 0 else False
    if i in byzantine_nodes:
        node = TendermintNodeByzantineCollude(
            i, n, round_time, mq, mq, collusion_tracker, verbose
        )
    else:
        node = algorithm.TendermintNode(i, n, round_time, mq, mq, verbose)
    nodes[i] = node

for i in range(n):
    for j in range(n):
        if i == j:
            continue
        nodes[i].add_peer(j)

for i in nodes:
    # Start them off...
    nodes[i].start_round(0)

mq.run()
