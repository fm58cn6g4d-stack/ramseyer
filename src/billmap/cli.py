"""billmap command line."""
from __future__ import annotations

from urllib.parse import urljoin

import json

import typer

from billmap import config
from billmap.data import olrc
from billmap.data.http import Fetcher
from billmap.data.indexer import Indexer

app = typer.Typer(no_args_is_help=True, add_completion=False)


@app.callback()
def main() -> None:
    """Map draft bills onto the U.S. Code."""


@app.command()
def sync(force: bool = typer.Option(False, help="Rebuild the release point even if already indexed.")) -> None:
    """Fetch the current OLRC release point and index every title."""
    cfg = config.load()
    f = Fetcher(cfg)
    page_url = urljoin(cfg.olrc_base, "download.html")
    rp = olrc.parse_release_point(f.get(page_url, refresh=True).text(), page_url)
    if rp.label != cfg.release_pin:
        typer.echo(f"note: OLRC is at {rp.label}; billmap.toml pins {cfg.release_pin}. "
                   f"Indexing {rp.label}; update the pin to use it.")
    typer.echo(f"release point {rp.label} ({rp.date}); downloading {rp.xml_all}")
    zip_resp = f.get(rp.xml_all)
    if zip_resp.status != 200:
        raise typer.Exit(f"download failed: HTTP {zip_resp.status}")
    ix = Indexer(cfg.index_path)
    if force:
        row = ix.db.execute("SELECT id FROM release_points WHERE label=?", (rp.label,)).fetchone()
        if row:
            ix.drop_release_point(row[0])
    rp_id = ix.load_release_point(zip_resp.path, rp.label, rp.date, rp.xml_all, rp.currency, log=typer.echo)
    xhtml_url = rp.xml_all.replace("/xml_uscAll@", "/htm_uscAll@")
    x_resp = f.get(xhtml_url)
    if x_resp.status != 200:
        raise typer.Exit(f"XHTML edition download failed: HTTP {x_resp.status}")
    counts = ix.cross_check_xhtml(rp_id, x_resp.path)
    typer.echo("XHTML cross-check: " + ", ".join(f"{k} {v:,}" for k, v in counts.items()))
    ix.mark_complete(rp_id)
    prior = ix.db.execute("SELECT id, label FROM release_points WHERE complete=1 ORDER BY id DESC").fetchall()
    for old_id, label in prior[1 + cfg.keep_prior:]:
        typer.echo(f"dropping release point {label} (keep_prior={cfg.keep_prior})")
        ix.drop_release_point(old_id)
    typer.echo(f"indexed {rp.label} into {cfg.index_path}")


@app.command("serve-mcp")
def serve_mcp() -> None:
    """Start the statute MCP server on stdio."""
    from billmap.mcp_server.server import main as serve
    serve()


@app.command()
def statute(tool: str = typer.Argument(..., help="resolve_cite, get_section, cited_by, search, ..."),
            args: list[str] = typer.Argument(None, help="key=value pairs, e.g. citation='4 USC 1'")) -> None:
    """Run a statute-server tool from the command line and print its JSON result."""
    from billmap.statute import TOOLS, StatuteService, call
    if tool not in TOOLS:
        raise typer.BadParameter(f"tool must be one of {', '.join(TOOLS)}")
    kwargs = {}
    for a in args or []:
        k, _, v = a.partition("=")
        kwargs[k] = {"true": True, "false": False}.get(v.lower(), int(v) if v.isdigit() else v)
    typer.echo(json.dumps(call(StatuteService(), tool, **kwargs), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    app()
