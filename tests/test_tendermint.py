import time
from tendermint import algorithm
from tendermint import message_queue

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
    """
    Propose invalid blocks, but otherwise behave normally
    """

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


class TendermintNodeNilPrecommit(algorithm.TendermintNode):
    """
    Propose ABCD for a block
    Vote NIL for precommit on round 0, otherwise behave normally
    """

    def __init__(self, node_id, num_nodes, round_time, mq, scheduler, verbose=False):
        super().__init__(node_id, num_nodes, round_time, mq, scheduler, verbose)

    def broadcast_proposal(self, h, round, _proposal, valid_round):
        # Hardcode a specific proposal for round 0 so we can test it
        if round == 0:
            proposal = "ABCD"
        else:
            proposal = _proposal

        msg = {
            "msg_type": "PROPOSAL",
            "sender": self.node_id,
            "h": h,
            "round": round,
            "proposal": proposal,
            "valid_round": valid_round,
        }
        self.broadcast(msg)

    def broadcast_precommit(self, h, round, id_v):
        if round == 0:
            msg = {
                "msg_type": "PRECOMMIT",
                "sender": self.node_id,
                "h": h,
                "round": round,
                "id_v": algorithm.NIL,
            }
            self.broadcast(msg)
        else:
            super().broadcast_precommit(h, round, id_v)


class MessageQueueCutoff(message_queue.MessageQueue):
    def __init__(self, nodes, last_round):
        super().__init__(nodes, 0)
        # This will be the last round we process
        self.last_round = last_round

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
    # All nodes should only have one block
    num_blocks = {len(nodes[i].decision) for i in range(len(nodes))}
    assert num_blocks == {1}
    decisions = {nodes[i].decision.get(0, None) for i in range(len(nodes))}
    assert None not in decisions
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
    node = TendermintNodeInvalid(0, n, round_time, mq, mq, verbose=True)
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

    # All nodes should only have one block
    num_blocks = {len(nodes[i].decision) for i in range(len(nodes))}
    assert num_blocks == {1}
    decisions = {nodes[i].decision.get(0, None) for i in range(len(nodes))}
    assert None not in decisions
    assert len(decisions) == 1
    decision = list(decisions)[0]
    assert nodes[0].valid(decision)


def test_prevote_fails_for_some_a():
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

    Case A: the same block is eventually proposed again and we get a QC
    This will happen if we have so many nodes with a prevote QC that we
    cannot reach a prevote QC on another block
    """
    n = 4

    nodes = {}
    # We'll need node 3 to propose it to succeed
    last_round = 3
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

    # nodes 0 and 3 saw the QC in round 0, other two did not
    # So nodes 1 and 2 should propose and fail, then node 3 should propose ABCD
    # and it will be accepted
    for node_id in [0, 3]:
        nodes[node_id].locked_value = "ABCD"
        nodes[node_id].locked_round = 0
        nodes[node_id].valid_value = "ABCD"
        nodes[node_id].valid_round = 0

    for i in nodes:
        nodes[i].start_round(1)

    mq.run()
    # All nodes should only have one block
    num_blocks = {len(nodes[i].decision) for i in range(len(nodes))}
    assert num_blocks == {1}
    decisions = {nodes[i].decision.get(0, None) for i in range(len(nodes))}
    assert None not in decisions
    assert len(decisions) == 1
    decision = list(decisions)[0]
    assert decision == "ABCD"


def test_prevote_fails_for_some_b():
    """
    Case B - a new block is proposed and accepted
    This will happen if we only have a few nodes with a prevote QC,
    so it's possible for the other nodes to reach a QC on a different block
    """
    n = 4

    nodes = {}
    # Only will take one round (and we'll start on round 1)
    last_round = 1
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

    # only node 0 saw the QC in round 0
    # So it should be overruled when a different block is proposed on the next round
    nodes[0].locked_value = "ABCD"
    nodes[0].locked_round = 0
    nodes[0].valid_value = "ABCD"
    nodes[0].valid_round = 0

    for i in nodes:
        nodes[i].start_round(1)

    mq.run()
    # All nodes should only have one block
    num_blocks = {len(nodes[i].decision) for i in range(len(nodes))}
    assert num_blocks == {1}
    decisions = {nodes[i].decision.get(0, None) for i in range(len(nodes))}
    assert None not in decisions
    assert len(decisions) == 1
    decision = list(decisions)[0]
    # So here it should NOT be ABCD...
    assert decision != "ABCD"
    # And the locked_value should be cleared out for all nodes
    for node_id in nodes:
        assert nodes[node_id].locked_value == algorithm.NIL
        assert nodes[node_id].locked_round == -1
        assert nodes[node_id].valid_value == algorithm.NIL
        assert nodes[node_id].valid_round == -1


def test_prevote_succeeds_precommit_fails_for_all():
    """
    Simpler version of the situation where prevote fails:
    All honest nodes will have locked onto a particular value, and we'll only
    able to progress when that value is reproposed in a future round
    """
    n = 4

    nodes = {}
    # Should take two rounds, 0 and 1
    last_round = 1
    round_time = 0.01
    mq = MessageQueueCutoff(nodes, last_round)

    for i in range(n):
        node = TendermintNodeNilPrecommit(i, n, round_time, mq, mq, verbose=False)
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
    # All nodes should only have one block
    num_blocks = {len(nodes[i].decision) for i in range(len(nodes))}
    assert num_blocks == {1}
    decisions = {nodes[i].decision.get(0, None) for i in range(len(nodes))}
    assert None not in decisions
    assert len(decisions) == 1
    decision = list(decisions)[0]
    # We hacked our proposals so ABCD is proposed round0, DEFG round 1
    # We should reuse ABCD for round 2 once precommit for ABCD fails
    assert decision == "ABCD"
    assert nodes[0].valid(decision)


def test_prevote_succeeds_precommit_fails_for_some_a():
    """
    Since we have a prevote QC, that WILL be the value for next rounds, even if
    only one node sees it.
    If a node already has the precommit QC:
        Not completely sure - think the block would be considered invalid and it
        would vote Nil for the same block in future rounds, but then we'd need
        some mechanism to let other nodes catch up

    If a node doesn't have the precommit QC:
        It will have the prevote QC, so it will repropose that for future rounds

    Case A - a minority of nodes see the prevote QC.  Since we had a prevote QC,
    eventually they should repropose that block.
    """
    n = 4

    nodes = {}
    # Two rounds for them all to get it
    last_round = 2
    mq = MessageQueueCutoff(nodes, last_round)
    round_time = 0.01

    for i in range(n):
        verbose = i == 0
        node = algorithm.TendermintNode(i, n, round_time, mq, mq, verbose)
        nodes[i] = node

    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            nodes[i].add_peer(j)

    # only node 1 saw the QC in round 0
    # It will propose a new block in the next round - but it will be rejected by
    # other nodes.  Then when it's their turn, they'll repropose that block and
    # it will be accepted
    for node_id in [0, 2, 3]:
        nodes[node_id].locked_value = "ABCD"
        nodes[node_id].locked_round = 0
        nodes[node_id].valid_value = "ABCD"
        nodes[node_id].valid_round = 0

    # And node 0 got the QC, so stored it as a block
    nodes[1].decision[0] = "ABCD"
    nodes[1].h += 1

    # Starting on round 1...
    for i in nodes:
        # Start them off...
        nodes[i].start_round(1)

    mq.run()

    # All nodes should only have one block
    num_blocks = {len(nodes[i].decision) for i in range(len(nodes))}
    assert num_blocks == {1}
    decisions = {nodes[i].decision.get(0, None) for i in range(len(nodes))}
    assert None not in decisions
    assert len(decisions) == 1
    decision = list(decisions)[0]
    # So here it should be ABCD for all nodes
    assert decision == "ABCD"
    # And the locked_value should be cleared out for all nodes
    for node_id in nodes:
        assert nodes[node_id].locked_value == algorithm.NIL
        assert nodes[node_id].locked_round == -1
        assert nodes[node_id].valid_value == algorithm.NIL
        assert nodes[node_id].valid_round == -1


def test_prevote_succeeds_precommit_fails_for_some_b():
    """
    Case B - a majority of nodes see the precommit QC.  They will be able to
    create a new block without needing the nodes that did not see the QC.
    So some nodes will get left behind and will have to catch up, but
    they should still be able to participate in future rounds

    Think this test is wrong - the node without the QC should not be able
    to repropose the block
    """
    n = 4

    nodes = {}
    # First round it should catch up
    last_round = 1
    mq = MessageQueueCutoff(nodes, last_round)
    round_time = 0.01

    for i in range(n):
        verbose = i == 0
        node = algorithm.TendermintNode(i, n, round_time, mq, mq, verbose)
        nodes[i] = node

    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            nodes[i].add_peer(j)

    # Inverse of scenario above - 3 of them have it, other not
    for node_id in [0, 2, 3]:
        # And node 0 got the QC, so stored it as a block
        nodes[node_id].decision[0] = "ABCD"
        nodes[node_id].h += 1

    nodes[1].locked_value = "ABCD"
    nodes[1].locked_round = 0
    nodes[1].valid_value = "ABCD"
    nodes[1].valid_round = 0

    for i in nodes:
        nodes[i].start_round(1)

    mq.run()

    # All nodes should only have one block
    num_blocks = {len(nodes[i].decision) for i in range(len(nodes))}
    assert num_blocks == {1}
    decisions = {nodes[i].decision.get(0, None) for i in range(len(nodes))}
    assert None not in decisions
    assert len(decisions) == 1
    decision = list(decisions)[0]
    # So here it should be ABCD for all nodes
    assert decision == "ABCD"
    # And the locked_value should be cleared out for all nodes
    for node_id in nodes:
        assert nodes[node_id].locked_value == algorithm.NIL
        assert nodes[node_id].locked_round == -1
        assert nodes[node_id].valid_value == algorithm.NIL
        assert nodes[node_id].valid_round == -1
