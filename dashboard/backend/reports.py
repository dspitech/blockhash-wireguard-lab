#!/usr/bin/env python3
"""
BLOCKHash - reports.py
=========================================================
Deux responsabilites, toutes deux en LECTURE SEULE (aucune ecriture sur
wg0.conf, aucun besoin de la regle sudoers wgctl.py/wgops.py) :

  1) Generation d'un PDF tabulaire generique (`build_table_pdf`), utilise
     par /api/reports/pdf pour exporter le journal filtre (section 6) et
     par la vue Conformite pour exporter la liste des clients inactifs.
  2) Rapport hebdomadaire par email (`send_weekly_report`), reutilisant
     le canal e-mail deja configure dans alerts.py (voir README 7.9.3) -
     pas de configuration SMTP dupliquee.

Ce module tourne directement dans le process Flask (www-data), comme
alerts.py : il ne necessite pas d'etre invoque via sudo.
"""

import argparse
import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

import alerts
import store
from wgstate import load_live_peers

REPORTS_CONFIG_PATH = Path(os.environ.get("REPORTS_CONFIG_PATH", "/etc/blockhash/reports-config.json"))
DEFAULT_REPORTS_CONFIG = {"weekly_enabled": False, "to_addr": ""}


# ---------------------------------------------------------------------
# Configuration du rapport hebdomadaire
# ---------------------------------------------------------------------
def load_reports_config():
    cfg = dict(DEFAULT_REPORTS_CONFIG)
    if REPORTS_CONFIG_PATH.exists():
        try:
            cfg.update(json.loads(REPORTS_CONFIG_PATH.read_text()))
        except (json.JSONDecodeError, OSError):
            pass
    return cfg


def save_reports_config(partial):
    cfg = load_reports_config()
    for key in DEFAULT_REPORTS_CONFIG:
        if key in partial:
            cfg[key] = partial[key]
    REPORTS_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = REPORTS_CONFIG_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cfg, indent=2))
    tmp.replace(REPORTS_CONFIG_PATH)
    return cfg


# ---------------------------------------------------------------------
# PDF tabulaire generique
# ---------------------------------------------------------------------
# Import differe : uniquement necessaire cote Flask (venv, ou fpdf2 est
# installe via requirements.txt). Le cron du rapport hebdomadaire
# (send-weekly) tourne avec le python3 systeme et n'a besoin que du
# chemin e-mail ci-dessous - inutile de lui imposer cette dependance.
def _new_table_pdf(title, subtitle=""):
    from fpdf import FPDF
    from fpdf.enums import XPos, YPos

    class _TablePDF(FPDF):
        def header(self):
            self.set_font("Helvetica", "B", 14)
            self.cell(0, 10, title, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            if subtitle:
                self.set_font("Helvetica", "", 10)
                self.set_text_color(100, 100, 100)
                self.cell(0, 6, subtitle, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                self.set_text_color(0, 0, 0)
            self.ln(2)

        def footer(self):
            self.set_y(-12)
            self.set_font("Helvetica", "", 8)
            self.set_text_color(150, 150, 150)
            self.cell(0, 8, f"BLOCKHash - page {self.page_no()}", align="C")

    pdf = _TablePDF(orientation="L", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    return pdf


def build_table_pdf(title, subtitle, columns, rows, max_rows=2000):
    """columns: liste de libelles. rows: liste de listes (memes longueur
    que columns). max_rows evite un PDF demesure si l'export n'est pas
    filtre correctement en amont."""
    pdf = _new_table_pdf(title, subtitle)
    pdf.add_page()

    usable_width = pdf.w - pdf.l_margin - pdf.r_margin
    col_width = usable_width / max(len(columns), 1)

    pdf.set_font("Helvetica", "B", 9)
    pdf.set_fill_color(230, 230, 230)
    for col in columns:
        pdf.cell(col_width, 8, str(col), border=1, fill=True)
    pdf.ln()

    pdf.set_font("Helvetica", "", 8)
    for row in rows[:max_rows]:
        for value in row:
            text = str(value) if value is not None else ""
            pdf.cell(col_width, 7, text[:45], border=1)
        pdf.ln()

    if len(rows) > max_rows:
        pdf.ln(4)
        pdf.set_font("Helvetica", "I", 8)
        pdf.cell(0, 6, f"... {len(rows) - max_rows} ligne(s) supplementaire(s) non affichee(s).")

    return bytes(pdf.output())


# ---------------------------------------------------------------------
# Rapport hebdomadaire
# ---------------------------------------------------------------------
def build_weekly_summary(now=None):
    now = now or datetime.now(tz=timezone.utc)
    week_ago_ts = int((now - timedelta(days=7)).timestamp())

    peers = load_live_peers()
    enabled_peers = [p for p in peers if p["enabled"]]
    total_rx = sum(p["rx_bytes"] for p in peers)
    total_tx = sum(p["tx_bytes"] for p in peers)
    inactive_7d = [
        p["name"]
        for p in enabled_peers
        if p["seconds_since_handshake"] is None or p["seconds_since_handshake"] > 7 * 86400
    ]
    alerts_week = [a for a in store.list_alerts(limit=1000)["rows"] if a["ts"] >= week_ago_ts]

    lines = [
        f"Rapport hebdomadaire BLOCKHash - semaine du {(now - timedelta(days=7)).strftime('%d/%m/%Y')} au {now.strftime('%d/%m/%Y')}",
        "",
        f"Clients actifs : {len(enabled_peers)} / {len(peers)} configures au total",
        f"Volume cumulé depuis le démarrage du tunnel : {total_rx / 1_000_000:.1f} Mo reçus, {total_tx / 1_000_000:.1f} Mo émis",
        f"Alertes déclenchées cette semaine : {len(alerts_week)}",
        f"Clients actifs sans connexion depuis plus de 7 jours : {len(inactive_7d)}",
    ]
    if inactive_7d:
        lines.append("  -> " + ", ".join(inactive_7d[:25]) + (", ..." if len(inactive_7d) > 25 else ""))

    if alerts_week:
        lines.append("")
        lines.append("Détail des alertes de la semaine :")
        for a in alerts_week[:30]:
            ts = datetime.fromtimestamp(a["ts"], tz=timezone.utc).strftime("%d/%m %H:%M")
            lines.append(f"  [{ts}] {a['source']} - {a['message']}")
        if len(alerts_week) > 30:
            lines.append(f"  ... et {len(alerts_week) - 30} de plus.")

    lines.append("")
    lines.append("-- Rapport généré automatiquement par BLOCKHash, voir le dashboard pour le détail.")
    return "\n".join(lines)


def send_weekly_report(now=None):
    cfg = load_reports_config()
    if not cfg.get("weekly_enabled"):
        return {"ok": True, "sent": False, "reason": "Rapport hebdomadaire désactivé."}

    alerts_cfg = alerts.load_config()
    to_addr = cfg.get("to_addr") or alerts_cfg["channels"]["email"].get("to_addr")
    if not to_addr:
        return {"ok": False, "sent": False, "reason": "Aucun destinataire configuré."}

    email_cfg = dict(alerts_cfg["channels"]["email"])
    if not email_cfg.get("smtp_host"):
        return {"ok": False, "sent": False, "reason": "Aucun serveur SMTP configuré (onglet Alertes)."}
    email_cfg["to_addr"] = to_addr

    body = build_weekly_summary(now=now)
    alerts.send_email(email_cfg, "BLOCKHash - Rapport hebdomadaire", body)
    return {"ok": True, "sent": True, "to": to_addr}


def main():
    parser = argparse.ArgumentParser(description="BLOCKHash - reports.py")
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("send-weekly", help="Envoie le rapport hebdomadaire si active")
    sub.add_parser("preview-weekly", help="Affiche le contenu du rapport sans l'envoyer")
    args = parser.parse_args()

    if args.action == "send-weekly":
        try:
            print(json.dumps(send_weekly_report()))
        except Exception as exc:
            print(json.dumps({"ok": False, "error": str(exc)}))
    elif args.action == "preview-weekly":
        print(build_weekly_summary())


if __name__ == "__main__":
    main()
