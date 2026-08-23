"""Grounded generation for a single selected document (Phase 4).

Every factual answer is grounded in retrieved evidence and cites only ids from
that request's allow-list. Document text is untrusted input: instructions inside
a document never change system policy, request tools, expose secrets, or widen
retrieval scope.
"""
