import os
import re
import math
import time
import datetime
import threading
from zoneinfo import ZoneInfo
import requests
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# Les cles viennent maintenant des variables d'environnement (configurees sur Render),
# plus jamais ecrites en dur dans le code.
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
FOOTBALL_TOKEN = os.environ["FOOTBALL_TOKEN"]
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID")  # si non defini, le bot reste ouvert a tous
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")


def sb_headers():
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }


def label_resultat(p_win, p_draw, p_lose):
    m = max(p_win, p_draw, p_lose)
    if m == p_win:
        return "victoire_a"
    if m == p_draw:
        return "nul"
    return "victoire_b"


def enregistrer_pronostic(sport, equipe_a, equipe_b, id_a, id_b, p_win, p_draw, p_lose, best):
    if not SUPABASE_URL:
        return
    try:
        requests.post(
            f"{SUPABASE_URL}/rest/v1/pronostics",
            headers={**sb_headers(), "Prefer": "return=minimal"},
            json={
                "sport": sport,
                "equipe_a": equipe_a,
                "equipe_b": equipe_b,
                "id_a": str(id_a),
                "id_b": str(id_b),
                "p_win": p_win,
                "p_draw": p_draw,
                "p_lose": p_lose,
                "score_predit": f"{best[1]}-{best[2]}",
            },
            timeout=10,
        )
    except Exception:
        pass


def est_autorise(chat_id):
    if not ADMIN_CHAT_ID:
        return True
    return str(chat_id) == str(ADMIN_CHAT_ID)

API_URL = "https://api.football-data.org/v4"
HEADERS = {"X-Auth-Token": FOOTBALL_TOKEN}
LIGUE_MOYENNE = 1.4
HEURE_ENVOI = datetime.time(hour=9, minute=0, tzinfo=ZoneInfo("Africa/Abidjan"))
HEURE_ENVOI_HOCKEY = datetime.time(hour=15, minute=0, tzinfo=ZoneInfo("Africa/Abidjan"))

COMPETITIONS = ["PL", "BL1", "SA", "PD", "FL1", "CL", "DED", "PPL", "ELC", "BSA", "WC", "EC"]
COMPETITIONS_ID = ["2021", "2002", "2019", "2014", "2015", "2001", "2003", "2017", "2016", "2013", "2000", "2018"]
EQUIPES = {}

# ---------- Hockey (NHL) ----------
NHL_URL = "https://api-web.nhle.com/v1"
LIGUE_MOYENNE_NHL = 3.0  # moyenne de buts par equipe et par match en NHL

NHL_EQUIPES = {
    "anaheim": "ANA", "ducks": "ANA", "anaheim ducks": "ANA",
    "boston": "BOS", "bruins": "BOS", "boston bruins": "BOS",
    "buffalo": "BUF", "sabres": "BUF", "buffalo sabres": "BUF",
    "calgary": "CGY", "flames": "CGY", "calgary flames": "CGY",
    "carolina": "CAR", "hurricanes": "CAR", "carolina hurricanes": "CAR",
    "chicago": "CHI", "blackhawks": "CHI", "chicago blackhawks": "CHI",
    "colorado": "COL", "avalanche": "COL", "colorado avalanche": "COL",
    "columbus": "CBJ", "blue jackets": "CBJ", "columbus blue jackets": "CBJ",
    "dallas": "DAL", "stars": "DAL", "dallas stars": "DAL",
    "detroit": "DET", "red wings": "DET", "detroit red wings": "DET",
    "edmonton": "EDM", "oilers": "EDM", "edmonton oilers": "EDM",
    "florida": "FLA", "panthers": "FLA", "florida panthers": "FLA",
    "los angeles": "LAK", "la kings": "LAK", "kings": "LAK", "los angeles kings": "LAK",
    "minnesota": "MIN", "wild": "MIN", "minnesota wild": "MIN",
    "montreal": "MTL", "canadiens": "MTL", "montreal canadiens": "MTL",
    "nashville": "NSH", "predators": "NSH", "nashville predators": "NSH",
    "new jersey": "NJD", "devils": "NJD", "new jersey devils": "NJD",
    "islanders": "NYI", "new york islanders": "NYI",
    "rangers": "NYR", "new york rangers": "NYR",
    "ottawa": "OTT", "senato…
