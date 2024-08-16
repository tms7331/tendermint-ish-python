# Tendermint-ish

A simplified implementation of Tendermint, designed primarily as a learning resource to better understand the decision-making processes of nodes in the Tendermint consensus protocol. This is not a fully robust implementation and definitely contains unhandled edge cases.

I aimed to closely follow the pseudocode outlined in ["The Latest Gossip on BFT Consensus"](https://arxiv.org/pdf/1807.04938).  There are some differences between this implementation and the pseudocode in Tim Roughgarden's [Foundations of Blockchains lecture on Tendermint](https://timroughgarden.github.io/fob21/l/l7.pdf).


## Running the Code

### Dependencies

None unless you want to run the tests.  For the tests, you'll need `pytest`. Install it via pip:

```bash
pip install pytest
```

And then run the tests, which check for correct behavior in basic scenarios.

```bash
pytest tests
```

### Execution

There are three scripts available to showcase how Tendermint will work in different scenarios.

1. **Successful Block Building**  
   Shows successful consensus with no Byzantine nodes (and would work with up to 1/3 Byzantine nodes).
   
   ```bash
   python tendermint/run_good.py
   ```

2. **Safety Failure**  
   Shows a scenario where 50% of the nodes are Byzantine, and coordinate their messaging, leading to a safety failure.
   
   ```bash
   python tendermint/run_byzantine1.py
   ```

3. **Liveness Failure**  
   Shows a scenario where 50% of the nodes are Byzantine, and return random block proposals and votes, resulting in a liveness failure.
   
   ```bash
   python tendermint/run_byzantine2.py
   ```

## Tendermint Resources

To better understand Tendermint, you can refer to the following resources:

- [The Latest Gossip on BFT Consensus](https://arxiv.org/pdf/1807.04938)
- [Foundations of Blockchains Lecture #7: The Tendermint Protocol](https://timroughgarden.github.io/fob21/l/l7.pdf)

## Insights and Reflections

The main motivation for working through this implementation was to resolve several lingering questions after reading through the Tendermint papers:

### 1. Why do we need more than one round of voting?

**Answer:**  
In a single round of voting, timing delays could result in only one node seeing the quorum certificate (QC) and committing to it. In the next round, other nodes could propose a different block and build a QC for it. This leads to a **safety violation**—nodes have committed to different blocks at the same block height.

To address this, it seems like it might work if nodes locked onto the block they voted for. However, if this was adopted, a Byzantine proposer could send different blocks to different portions of the network.  As different portions of the network locked onto different blocks, this would result in a **liveness violation**

### 2. Why do we need a 2f+1 majority? Why not just require > 50% of the vote?

**Answer:**  
If we only required a > 50% vote for a QC, and so allowed up to 50% of nodes to be Byzantine, the Byzantine nodes could collude and send conflicting information to different nodes.  This is the same behavior shown in `run_byzantine1`.  A concrete example:

- Suppose there are 100 nodes, and 49 are Byzantine.
- A Byzantine proposer proposes block B to the first half of the honest nodes ([0..24]), and block B' to the other half ([25..50])
- All Byzantine nodes match this behavior in each voting round, sending votes for B to ([0..24]) and B' to ([25..50]). 
- Nodes [0..24] see 49+25=74 votes for block B, while nodes [25..50] see 49+26=75 votes for block B'.
- Honest nodes of the network think they've reached consensus on different blocks, resulting in a **safety violation**.

We require 2f+1 votes because it is the first point at which this attack will not work.