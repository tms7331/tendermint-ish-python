from tendermint import algorithm
from tendermint import message_queue
import time

"""
TEST SUITE EXPLANATION:

Assuming we have more than 2/3 honest nodes, there are five scenarios that can happen:

-prevote succeeds, precommit succeeds for all nodes
-prevote fails for all nodes
-prevote fails for some nodes, succeeds for others
-prevote succeeds, precommit fails for all nodes
-prevote succeeds, precommit fails for some nodes, succeeds for others

A voting round can fail for some nodes and succeed for others if only a subset of 
nodes see a QC, which can happen due to network latency

We have a test case for each of these scenarios
"""


class TendermintNodeInvalid(algorithm.TendermintNode):
    def __init__(self, node_id, num_nodes, round_time, mq, scheduler, verbose=False):
        super().__init__(node_id, num_nodes, round_time, mq, scheduler, verbose)

    def start_round(self, round):
        """
        If it's our turn to propose, propose an invalid block, otherwise behave normally
        """
        self.round = round
        self.step = "propose"

        if self.proposer(self.h, self.round) == self.node_id:
            # Propose a bad block!
            proposal = "INVALID_BLOCK"
            self.broadcast_proposal(self.h, round, proposal, self.valid_round)
            self.step = "prevote"
        else:
            self.schedule_ontimeout_proposal(self.h, self.round)


class MessageQueueCutoff(message_queue.MessageQueue):
    def __init__(self, nodes, last_round):
        super().__init__(nodes)
        # This will be the last round we process
        self.last_round = last_round

    def run(self):
        while True:
            if not self.q:
                break
            (node, message) = self.q.pop(0)
            self.process_message(node, message)

    def run(self):
        while True:
            if self.q.empty():
                break
            (ts, node_id, message_i) = self.q.get()
            # Might be a scheduled message - need to wait for those
            now = time.time()
            if now < ts:
                time.sleep(ts - now)
            message = self.message_dict.pop(message_i)
            self.process_message(node_id, message)

    def send_message(self, node_id, message):
        if message["round"] <= self.last_round:
            self.message_dict[self.message_i] = message
            # prioritize scheduled messages that are due to run by using time.time()
            self.q.put((time.time(), node_id, self.message_i))
            self.message_i += 1

    def schedule_message(self, node_id, message, scheduled_time):
        if message["round"] <= self.last_round:
            self.message_dict[self.message_i] = message
            self.q.put((scheduled_time, node_id, self.message_i))
            self.message_i += 1


def test_prevote_succeeds_precommit_succeeds():
    """
    The "good" case - Every node should build prevote and precommit QCs, and
    build the same block
    """
    n = 4

    nodes = {}
    # Only will take one round
    last_round = 0
    mq = MessageQueueCutoff(nodes, last_round)
    round_time = 0.01

    for i in range(n):
        node = algorithm.TendermintNode(i, n, round_time, mq, mq)
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
    decisions = {nodes[i].decision.get(0, None) for i in range(len(nodes))}
    assert "None" not in decisions
    assert len(decisions) == 1
    decision = list(decisions)[0]
    assert nodes[0].valid(decision)


def test_prevote_fails_for_all():
    """
    Round 0 should fail to produce a block
    We should have no locked/valid values or rounds
    Round 1 should produce a block instead
    """
    n = 4

    nodes = {}
    # Should take two rounds now
    last_round = 1
    round_time = 0.01
    mq = MessageQueueCutoff(nodes, last_round)

    # Node 0 will propose a bad block, after that will be have normally
    node = TendermintNodeInvalid(0, n, round_time, mq, mq, verbose=False)
    nodes[0] = node
    # Other nodes are fine
    for i in range(1, n):
        node = algorithm.TendermintNode(i, n, round_time, mq, mq, verbose=False)
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
    decisions = {nodes[i].decision.get(0, None) for i in range(len(nodes))}
    assert "None" not in decisions
    assert len(decisions) == 1
    decision = list(decisions)[0]
    assert nodes[0].valid(decision)


def test_prevote_fails_for_some():
    """
    Tricky scenario -
    For nodes where it fails, we should go onto next round
        We'll accept any valid block for the next round
    For nodes where it passes - we'll go onto next round when precommit fails
        However we'll have locked onto that value
        We will reject all prevotes for other values
        In the case that enough nodes are locked that we can't get a prevote QC
        on any other value, we'll have to loop around until we reach one of these
        nodes, who will repropose the block

    Other edge case -- what if byzantine nodes then commit it?
    Think we'll be overruled in that case, which is fine
    """
    pass


def test_prevote_succeeds_precommit_fails_for_all():
    """
    Simpler version of the situation where prevote fails:
    all honest nodes will have locked onto the value
    We'll only be able to progress when that value is reproposed in a future
    round
    """
    pass


def test_prevote_succeeds_precommit_fails_for_some():
    """
    Since we have a prevote QC, that WILL be the value for next rounds
    If a node already has the precommit QC:
        it will vote Nil for future rounds (???)
    If a node doesn't have the precommit QC:
        It will have the prevote QC, so itw ill repropose that for future rounds
    """
    pass
