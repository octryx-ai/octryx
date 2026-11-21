"""Answer evidence enforcement: a final answer cites this turn's tool evidence with openable links.

``evidence`` reads the turn's sources, ``answer_blocks`` splits the answer, ``check`` decides and
records, ``texts`` holds the catalog-keyed guard texts. The runtime boundary that applies it is
``agent/loops/response/_loop_answer_evidence``.
"""
