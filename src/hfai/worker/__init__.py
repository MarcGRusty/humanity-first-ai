"""The AI process: runs the model, separate from the guardian.

It can only exchange messages with the guardian (worker/protocol.py). It has
no code that acts in the world. Until milestone M3, only the MOCK worker
(worker/mock.py) exists.
"""
