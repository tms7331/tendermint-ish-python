import string
import random
import algorithm
import message_queue

"""
LIVENESS FAILURE EXAMPLE
If more than 1/3 of nodes are byzantine and send random votes/proposals, we won't
ever be able to get a QC, and so we'll never be able to produce a block
"""


class TendermintNodeByzantineRandom(algorithm.TendermintNode):
    """
    A tendermint node which random values for proposals, prevotes, and precommits
    """

    def __init__(self, node_id, num_nodes, round_time, mq, scheduler, verbose=False):
        super().__init__(node_id, num_nodes, round_time, mq, scheduler, verbose)

    def broadcast_proposal(self, h, round, _proposal, valid_round):
        # len(8) string is considered invalid
        proposal = "".join(random.choice(string.ascii_letters) for _ in range(8))
        msg = {
            "msg_type": "PROPOSAL",
            "sender": self.node_id,
            "h": h,
            "round": round,
            "proposal": proposal,
            "valid_round": valid_round,
        }
        self.broadcast(msg)

    def broadcast_prevote(self, h, round, _id_v):
        id_v = int(random.random() * 1000)
        msg = {
            "msg_type": "PREVOTE",
            "sender": self.node_id,
            "h": h,
            "round": round,
            "id_v": id_v,
        }
        self.broadcast(msg)

    def broadcast_precommit(self, h, round, _id_v):
        id_v = int(random.random() * 1000)
        msg = {
            "msg_type": "PRECOMMIT",
            "sender": self.node_id,
            "h": h,
            "round": round,
            "id_v": id_v,
        }
        self.broadcast(msg)


n = 4
nodes = {}

byzantine_nodes = {2, 3}
round_time = 1
mq = message_queue.MessageQueue(nodes, round_time)

for i in range(n):
    verbose = True if i == 0 else False
    if i in byzantine_nodes:
        node = TendermintNodeByzantineRandom(i, n, round_time, mq, mq, verbose)
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
