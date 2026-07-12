"""CGI/ASP endpoint paths for the router's web API.

These are the same paths the router's own web UI calls. `NONCE` and `LOGIN` reflect the
nonce/cnonce challenge-response login used by this router's firmware (confirmed by reading
`Main_Login.asp`'s own JavaScript) rather than the older plain base64(user:pass) scheme some
other AsusWRT routers still use.
"""

from __future__ import annotations

NONCE = "get_Nonce.cgi"
LOGIN = "login_v2.cgi"
LOGOUT = "Logout.asp"
HOOK = "appGet.cgi"
APPLY = "applyapp.cgi"
