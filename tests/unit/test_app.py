"""M8: the local app's server: 127.0.0.1 only, a per-page token on analysis, reports served from their own folder."""
import json
import threading
import urllib.error
import urllib.request
from types import SimpleNamespace

import ramseyer.analyze as analyze_mod
from ramseyer.app import make_server


def test_the_app_analyzes_a_draft_and_serves_its_report(tmp_path, monkeypatch):
    fake = analyze_mod.Analysis(title="d.txt", release_point="1-1", input_hash="ab" * 32, generated="g", version="0",
                                counts={"CLEAN": 1}, committee_html="<p>print</p>", working_html="<p>work</p>",
                                docx=b"PK", instructions=[{"id": "s#0", "status": "CLEAN", "target": "t",
                                                           "source": "s", "detail": ""}])
    monkeypatch.setattr(analyze_mod, "resolver", lambda: SimpleNamespace(ix=SimpleNamespace(release_point="1-1")))
    monkeypatch.setattr(analyze_mod, "analyze", lambda name, data: fake)
    server = make_server(0, tmp_path)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        assert server.server_address[0] == "127.0.0.1"
        page = urllib.request.urlopen(base + "/").read().decode()
        token = page.split('const TOKEN = "')[1].split('"')[0]
        try:
            urllib.request.urlopen(urllib.request.Request(base + "/analyze?name=d.txt", data=b"x", method="POST",
                                                          headers={"Origin": base}))
            raise AssertionError("posted without the page's token")
        except urllib.error.HTTPError as e:
            assert e.code == 403
        req = urllib.request.Request(base + "/analyze?name=d.txt", data=b"x", method="POST",
                                     headers={"X-Token": token, "Origin": base})
        body = json.loads(urllib.request.urlopen(req).read())
        assert body["counts"] == {"CLEAN": 1}
        assert urllib.request.urlopen(f"{base}/report/{body['id']}/comparative.html").read() == b"<p>print</p>"
        try:
            urllib.request.urlopen(f"{base}/report/{body['id']}/run.json")
            raise AssertionError("served a file outside the print")
        except urllib.error.HTTPError as e:
            assert e.code == 404
    finally:
        server.shutdown()


def test_an_unsupported_draft_is_refused_with_a_reason():
    import pytest
    with pytest.raises(ValueError, match="Word drafts come with M7"):
        analyze_mod.draft_text("bill.docx", b"PK")


def test_a_rebound_domain_or_another_origin_is_refused(tmp_path, monkeypatch):
    # Review of #21: a page that rebinds its own domain to 127.0.0.1 (DNS rebinding) sends its own Host header; it
    # must not get the page (and its token), and a draft may be posted only from the app's own origin.
    import http.client
    monkeypatch.setattr(analyze_mod, "resolver", lambda: SimpleNamespace(ix=SimpleNamespace(release_point="1-1")))
    server = make_server(0, tmp_path)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    try:
        def call(method, path, headers, body=None):
            c = http.client.HTTPConnection("127.0.0.1", port)
            c.putrequest(method, path, skip_host=True)
            for k, v in headers.items():
                c.putheader(k, v)
            c.putheader("Content-Length", str(len(body or b"")))
            c.endheaders(body)
            r = c.getresponse()
            return r.status, r.read().decode(errors="replace")
        status, body = call("GET", "/", {"Host": f"attacker.example:{port}"})
        assert status == 403 and "TOKEN" not in body
        status, body = call("GET", "/", {"Host": f"localhost:{port}"})
        token = body.split('const TOKEN = "')[1].split('"')[0]
        status, _ = call("POST", "/analyze?name=d.txt", {"Host": f"127.0.0.1:{port}", "X-Token": token,
                                                         "Origin": "http://attacker.example"}, b"x")
        assert status == 403
        status, _ = call("POST", "/analyze?name=d.txt", {"Host": f"127.0.0.1:{port}", "X-Token": token}, b"x")
        assert status == 403                                    # no Origin at all
    finally:
        server.shutdown()
