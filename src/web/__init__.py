"""iter 025: stdlib-only local WebUI dashboard.

Module map:

* ``server`` — ThreadingHTTPServer + BaseHTTPRequestHandler. ``serve(host, port)``
  is the single entry point used by ``main.py web``.
* ``routes`` — pure ``(method, path) -> (status, headers, body)`` dispatcher.
* ``workspace_ctx`` — context manager that temporarily sets
  ``WORKSPACE_NAME`` so paths.py helpers resolve to the right workspace.
* ``reviews_aggregator`` — load all ``outputs/drafts/chapter_NN.meta.json``
  files for a workspace and roll them up into a single JSON blob.
* ``templates`` / ``static`` — HTML + embedded CSS/JS string constants.

iter 025 ships only GET endpoints; POST/PUT (wizard, settings) land in
iter 026.
"""
