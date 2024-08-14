import time
from queue import PriorityQueue


class MessageQueue:
    def __init__(self, nodes, round_time):
        self.nodes = nodes
        self.q = PriorityQueue()
        self.message_dict = {}
        self.message_i = 0

        ## Storing a view of chain state for our liveness checks
        self.block_height = 0
        self.round = 0
        ## Store round_time so we can schedule messages in a way that makes
        # for pretty printing
        self.start_time = time.time()
        self.round_time = round_time

    def run(self):
        count = 0
        while True:
            assert not self.q.empty(), "Empty queue!  Program stuck"
            (ts, node_id, message_i) = self.q.get()
            # Might be a scheduled message - need to wait for those
            now = time.time()
            if now < ts:
                time.sleep(ts - now)
            message = self.message_dict.pop(message_i)
            self.process_message(node_id, message)
            count += 1
            if count % 100 == 0:
                self.safety_check()
                self.liveness_check()

    def send_message(self, node_id, message):
        """
        Just adds it to queue
        """
        self.message_dict[self.message_i] = message
        # This logic prevents it from racing ahead to the next block once a block
        # is built, not sure this is what happens in real tendermint but it's
        # helpful for pretty printing output
        scheduled_time = max(
            time.time(), self.start_time + (message["round"]) * self.round_time
        )
        self.q.put((scheduled_time, node_id, self.message_i))
        self.message_i += 1

    def schedule_message(self, node_id, message, scheduled_time):
        """
        We're using single module for both message queue and scheduler
        This method should be implemented on any other scheduler
        """
        self.message_dict[self.message_i] = message
        self.q.put((scheduled_time, node_id, self.message_i))
        self.message_i += 1

    def process_message(self, node_id, message):
        self.nodes[node_id].process_message(message)

    def safety_check(self):
        """
        Make sure no nodes have different values (blocks) for any block height
        """
        # Every node should generally be on the same round, and 'round' upper
        # bounds height
        round = self.nodes[0].round
        for i in range(0, round):
            # It's ok if some blocks have fallen behind and have NIL/None
            decisions = {
                self.nodes[x].decision.get(i, None)
                for x in self.nodes
                if self.nodes[x].decision.get(i, None)
            }
            if len(decisions) > 1:
                dec_all = list(decisions)
                print("\n####### SAFETY VIOLATION!!! #######")
                # First print all blocks, then print specific information about violation
                for x in self.nodes:
                    self.nodes[x].print_blocks()
                for dec in dec_all:
                    matches = {
                        self.nodes[i].node_id
                        for i in self.nodes
                        if self.nodes[i].decision.get(i, None) == dec
                    }
                    print(f"NODES {matches} BLOCK HEIGHT {i} VALUE {dec}")
                raise Exception("Safety Violation!")

    def liveness_check(self):
        """
        If we went go through every node as a proposer and no block was created,
        we'll call it a liveness violation (even though in reality I think
        it's more subtle than this)
        """
        block_height = max([len(self.nodes[x].decision) for x in self.nodes])
        round = max([self.nodes[x].round for x in self.nodes])

        new_blocks = block_height - self.block_height
        rounds_passed = round - self.round
        # Check will only work if we have at least as many "rounds_passed" as
        # we have nodes
        if rounds_passed < len(self.nodes):
            return
        if new_blocks == 0:
            print("\n####### LIVENESS VIOLATION!!! #######")
            raise Exception("Liveness Violation!")

        self.block_height = block_height
        self.round = round
