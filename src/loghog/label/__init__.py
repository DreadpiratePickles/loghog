"""Stage 06: the one stage that calls a model.

Everything before this is arithmetic on a log. This asks a model one question
per selected record — *what would a good answer to this have to satisfy?* — and
the whole module is arranged around not trusting the answer, because a criterion
that reaches a goldens file becomes the definition of correct for every later
evaluation.
"""
