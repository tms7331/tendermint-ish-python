import algorithm
import message_queue

n = 4

nodes = {}

round_time = 1
mq = message_queue.MessageQueue(nodes, round_time)

for i in range(n):
    verbose = True if i == 0 else False
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
