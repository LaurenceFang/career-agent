#!/usr/bin/env python3
"""Local Gmail and Google Calendar connector with explicit OAuth and write gates."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "google_oauth_client.json"
TOKEN = ROOT / "config" / "google_oauth_token.json"
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.events",
]


def dependencies():
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_httplib2 import AuthorizedHttp
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
        import httplib2
        return Request, Credentials, InstalledAppFlow, build, AuthorizedHttp, httplib2
    except ImportError as exc:
        raise SystemExit("Install connector dependencies first: pip install -r requirements-connectors.txt") from exc


def credentials():
    Request, Credentials, InstalledAppFlow, *_ = dependencies()
    if not CONFIG.exists():
        raise SystemExit(f"Missing Google OAuth client file: {CONFIG}. Create it from config/google_oauth_client.example.json.")
    creds = Credentials.from_authorized_user_file(TOKEN, SCOPES) if TOKEN.exists() else None
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(CONFIG, SCOPES)
        creds = flow.run_local_server(port=0, open_browser=True)
    TOKEN.write_text(creds.to_json(), encoding="utf-8")
    return creds


def windows_proxy_info(httplib2):
    """Return the current user's HTTP proxy without persisting its address."""
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Internet Settings") as key:
            enabled, _ = winreg.QueryValueEx(key, "ProxyEnable")
            server, _ = winreg.QueryValueEx(key, "ProxyServer")
        if not enabled or not server:
            return None
        entries = str(server).split(";")
        selected = next((entry.split("=", 1)[1] for entry in entries if entry.lower().startswith("https=")), None)
        selected = selected or next((entry.split("=", 1)[1] for entry in entries if entry.lower().startswith("http=")), None)
        selected = selected or str(server)
        parsed = urlparse(selected if "://" in selected else f"http://{selected}")
        if not parsed.hostname or not parsed.port:
            return None
        return httplib2.ProxyInfo(
            httplib2.socks.PROXY_TYPE_HTTP,
            parsed.hostname,
            parsed.port,
            proxy_rdns=True,
        )
    except (OSError, ValueError):
        return None


def google_service(api, version):
    _, _, _, build, AuthorizedHttp, httplib2 = dependencies()
    proxy_info = windows_proxy_info(httplib2)
    http = httplib2.Http(proxy_info=proxy_info) if proxy_info else httplib2.Http()
    return build(api, version, http=AuthorizedHttp(credentials(), http=http), cache_discovery=False)


def gmail_scan(args):
    service = google_service("gmail", "v1")
    query = "newer_than:90d (interview OR assessment OR application OR offer OR rejected OR rejection)"
    response = service.users().messages().list(userId="me", q=query, maxResults=args.limit).execute()
    rows = []
    for item in response.get("messages", []):
        msg = service.users().messages().get(userId="me", id=item["id"], format="metadata", metadataHeaders=["From", "Subject", "Date"]).execute()
        headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
        subject = headers.get("subject", "")
        snippet = msg.get("snippet", "")
        signal = classify_signal(subject, snippet)
        rows.append({"id": item["id"], "thread_id": msg.get("threadId"), "from": headers.get("from"), "subject": subject, "date": headers.get("date"), "snippet": snippet, "signal": signal, "status": "proposal_requires_review"})
    out = ROOT / "applications" / "gmail_status_proposals.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"scanned_at": datetime.now(timezone.utc).isoformat(), "query": query, "messages": rows}, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(f"Saved {len(rows)} read-only Gmail status proposals -> {out.relative_to(ROOT)}")


def classify_signal(subject: str, snippet: str) -> str:
    text = f"{subject} {snippet}".lower()
    if any(word in text for word in ("offer", "congratulations")):
        return "offer_requires_manual_decision"
    if any(word in text for word in ("rejected", "rejection", "unfortunately", "not moving forward")):
        return "rejected"
    if any(word in text for word in ("interview", "schedule a call", "meet with")):
        return "interview"
    if any(word in text for word in ("assessment", "coding challenge", "take-home")):
        return "assessment_requires_review"
    return "unmatched_requires_review"


def approve_proposal(args):
    if not args.confirm:
        raise SystemExit("Refusing to write an application outcome without --confirm.")
    proposals = ROOT / "applications" / "gmail_status_proposals.json"
    if not proposals.exists():
        raise SystemExit("Run gmail-scan first.")
    record = next((item for item in json.loads(proposals.read_text(encoding="utf-8")).get("messages", []) if item.get("id") == args.message_id), None)
    if record is None:
        raise SystemExit("Proposal message ID not found.")
    if record["signal"] not in {"interview", "rejected"}:
        raise SystemExit(f"Signal '{record['signal']}' requires a manual outcome decision; it cannot be auto-applied.")
    manifest = ROOT / "applications" / args.job_id / "application.json"
    if not manifest.exists():
        raise SystemExit("Local application archive not found.")
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["status"] = record["signal"]
    data.setdefault("events", []).append({"at": datetime.now(timezone.utc).isoformat(), "status": record["signal"], "source": "gmail_proposal_user_confirmed", "message_id": record["id"], "thread_id": record.get("thread_id")})
    manifest.write_text(json.dumps(data, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(f"Applied reviewed Gmail signal to local application: {args.job_id} -> {record['signal']}")


def calendar_draft(args):
    if not args.confirm:
        raise SystemExit("Refusing to create a Calendar event without --confirm.")
    start = datetime.fromisoformat(args.start.replace("Z", "+00:00"))
    end = start + timedelta(minutes=args.minutes)
    service = google_service("calendar", "v3")
    event = {"summary": args.title, "description": "Created by local Career Agent after explicit confirmation.", "start": {"dateTime": start.isoformat()}, "end": {"dateTime": end.isoformat()}}
    created = service.events().insert(calendarId="primary", body=event).execute()
    print(json.dumps({"created": True, "id": created.get("id"), "htmlLink": created.get("htmlLink")}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("authorize").set_defaults(func=lambda _args: credentials() and print("Google OAuth ready."))
    scan = sub.add_parser("gmail-scan"); scan.add_argument("--limit", type=int, default=50); scan.set_defaults(func=gmail_scan)
    approve = sub.add_parser("approve-gmail-proposal"); approve.add_argument("message_id"); approve.add_argument("job_id"); approve.add_argument("--confirm", action="store_true"); approve.set_defaults(func=approve_proposal)
    event = sub.add_parser("calendar-event"); event.add_argument("title"); event.add_argument("start", help="ISO-8601 date-time"); event.add_argument("--minutes", type=int, default=60); event.add_argument("--confirm", action="store_true"); event.set_defaults(func=calendar_draft)
    args = parser.parse_args(); args.func(args)


if __name__ == "__main__":
    main()
