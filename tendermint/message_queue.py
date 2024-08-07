import queue
import time


class QSchedule:
    def __init__(self):
        self.q_now = queue.Queue()
        self.q_sched = queue.Queue()

    def get(self):
        # If we're past the time for the scheduled queue, get that
        # otherwise pull from q_now
        if not self.q_sched.empty() and self.q_sched.queue[0][2] < time.time():
            (node, message, _) = self.q_sched.get()
            return (node, message)
        # If q_now is ever empty, we'll hang forever because program is single threaded
        # With our implementation this should never be empty
        assert not self.q_now.empty(), "Empty queue!  Program stuck"
        return self.q_now.get()

    def put(self, node, message, scheduled_time):
        """
        Just adds it to queue
        """
        if scheduled_time:
            self.q_sched.put((node, message, scheduled_time))
        else:
            self.q_now.put((node, message))


class MessageQueue:
    def __init__(self, nodes):
        self.nodes = nodes
        self.q = QSchedule()

        ## Storing a view of chain state for our liveness checks
        self.block_height = 0
        self.round = 0

    def run(self):
        count = 0
        while True:
            (node, message) = self.q.get()
            self.process_message(node, message)
            time.sleep(0.01)
            count += 1
            if count % 100 == 0:
                self.safety_check()
                self.liveness_check()

    def send_message(self, node, message):
        """
        Just adds it to queue
        """
        print("SENDING MESSAGE", node, message)
        self.q.put(node, message, 0)

    def schedule_message(self, node, message, scheduled_time):
        """
        We're using single module for both message queue and scheduler
        This method should be implemented on any other scheduler
        """
        self.q.put(node, message, scheduled_time)

    def process_message(self, node, message):
        print("PROCESS", node, message)
        self.nodes[node].process_message(message)

    def safety_check(self):
        """
        Make sure no nodes have different values (blocks) for any block height
        """
        # Every node should generally be on the same round, and 'round' upper bounds height
        round = self.nodes[0].round
        for i in range(0, round):
            decisions = {x.decision.get(i, None) for x in self.nodes}
            # It's ok if some blocks have fallen behind and have NIL/None
            if None in decisions:
                decisions.remove(None)
            if len(decisions) > 1:
                dec_all = list(decisions)
                print("####### SAFETY VIOLATION!!! #######")
                for dec in dec_all:
                    matches = [
                        x.node_id for x in self.nodes if x.decision.get(i, None) == dec
                    ]
                    print(f"NODES {matches} BLOCK HEIGHT {i} VALUE {dec}")
                raise Exception("Safety Violation!")

    def liveness_check(self):
        """
        If we went go through every node as a proposer and no block was created, we'll
        call it a liveness violation (even though in reality it's more subtle than this)
        """
        block_height = max([len(x.decision) for x in self.nodes])
        round = max([len(x.round) for x in self.nodes])

        new_blocks = block_height - self.block_height
        rounds_passed = round - self.round
        if new_blocks == 0 and rounds_passed > len(self.nodes):
            print("####### LIVENESS VIOLATION!!! #######")
            raise Exception("Liveness Violation!")

        self.block_height = block_height
        self.round = round
