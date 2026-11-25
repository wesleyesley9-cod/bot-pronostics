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
    "ottawa": "OTT", "senators": "OTT", "ottawa senators": "OTT",
    "philadelphia": "PHI", "flyers": "PHI", "philadelphia flyers": "PHI",
    "pittsburgh": "PIT", "penguins": "PIT", "pittsburgh penguins": "PIT",
    "san jose": "SJS", "sharks": "SJS", "san jose sharks": "SJS",
    "seattle": "SEA", "kraken": "SEA", "seattle kraken": "SEA",
    "st louis": "STL", "blues": "STL", "st louis blues": "STL",
    "tampa bay": "TBL", "lightning": "TBL", "tampa bay lightning": "TBL",
    "toronto": "TOR", "maple leafs": "TOR", "toronto maple leafs": "TOR",
    "utah": "UTA", "utah mammoth": "UTA", "mammoth": "UTA",
    "vancouver": "VAN", "canucks": "VAN", "vancouver canucks": "VAN",
    "vegas": "VGK", "golden knights": "VGK", "vegas golden knights": "VGK",
    "washington": "WSH", "capitals": "WSH", "washington capitals": "WSH",
    "winnipeg": "WPG", "jets": "WPG", "winnipeg jets": "WPG",
}


def saison_nhl():
    aujourdhui = datetime.date.today()
    if aujourdhui.month >= 7:
        return f"{aujourdhui.year}{aujourdhui.year + 1}"
    return f"{aujourdhui.year - 1}{aujourdhui.year}"


def trouver_equipe_nhl(nom_in):
    nom = nom_in.strip().lower()
    if nom in NHL_EQUIPES:
        return NHL_EQUIPES[nom], nom_in.strip()
    for cle, code in NHL_EQUIPES.items():
        if cle in nom or nom in cle:
            return code, nom_in.strip()
    return None, None


def stats_equipe_nhl(tricode, domicile=None):
    r = requests.get(f"{NHL_URL}/club-schedule-season/{tricode}/{saison_nhl()}", timeout=10)
    j = r.json()
    tous_les_matchs = [m for m in j.get("games", []) if m.get("gameState") == "OFF"]
    tous_les_matchs.sort(key=lambda m: m.get("gameDate", ""), reverse=True)

    if domicile is True:
        matchs = [m for m in tous_les_matchs if m["homeTeam"]["abbrev"] == tricode][:10]
    elif domicile is False:
        matchs = [m for m in tous_les_matchs if m["awayTeam"]["abbrev"] == tricode][:10]
    else:
        matchs = tous_les_matchs[:10]

    if domicile is not None and len(matchs) < 3:
        matchs = tous_les_matchs[:10]

    DECAY = 0.85  # les matchs les plus recents comptent plus (matchs[0] = le plus recent)
    bm_pond, be_pond, poids_total, n = 0.0, 0.0, 0.0, 0
    for i, m in enumerate(matchs):
        est_domicile = m["homeTeam"]["abbrev"] == tricode
        bm = m["homeTeam"]["score"] if est_domicile else m["awayTeam"]["score"]
        be = m["awayTeam"]["score"] if est_domicile else m["homeTeam"]["score"]
        poids = DECAY ** i
        bm_pond += bm * poids
        be_pond += be * poids
        poids_total += poids
        n += 1

    if n == 0:
        return LIGUE_MOYENNE_NHL, LIGUE_MOYENNE_NHL, 0
    return bm_pond / poids_total, be_pond / poids_total, n


# ---------- Mini serveur web, juste pour qu'UptimeRobot ait quelque chose a "pinger" ----------
web = Flask(__name__)


@web.route("/")
def accueil():
    return "Bot de pronostics en ligne."


@web.route("/run/foot")
def route_foot():
    if not ADMIN_CHAT_ID:
        return "ADMIN_CHAT_ID non configure", 400
    pronostics_jour(ADMIN_CHAT_ID)
    return "OK"


@web.route("/run/hockey")
def route_hockey():
    if not ADMIN_CHAT_ID:
        return "ADMIN_CHAT_ID non configure", 400
    pronostics_jour_hockey(ADMIN_CHAT_ID)
    return "OK"


@web.route("/run/verify")
def route_verify():
    verifier_pronostics()
    return "OK"


def lancer_serveur_web():
    port = int(os.environ.get("PORT", 10000))
    web.run(host="0.0.0.0", port=port)


# ---------- Logique du bot (identique a avant) ----------
def charger_equipes():
    print("Chargement des equipes...")
    for code in COMPETITIONS:
        try:
            r = requests.get(f"{API_URL}/competitions/{code}/teams", headers=HEADERS, timeout=10)
            data = r.json()
            for t in data.get("teams", []):
                for nom in (t.get("name"), t.get("shortName"), t.get("tla")):
                    if nom:
                        EQUIPES[nom.strip().lower()] = t["id"]
            print(f"  {code} : {len(data.get('teams', []))} equipes")
        except Exception as e:
            print(f"  {code} : erreur {e}")
        time.sleep(6)
    print(f"Total equipes chargees : {len(EQUIPES)}")


def poisson(lam: float, k: int) -> float:
    return math.exp(-lam) * (lam ** k) / math.factorial(k)


def trouver_equipe(nom_in):
    nom = nom_in.strip().lower()
    if nom in EQUIPES:
        return EQUIPES[nom], nom_in.strip()
    for cle, tid in EQUIPES.items():
        if cle in nom or nom in cle:
            return tid, nom_in.strip()
    return None, None


def stats_equipe(team_id, domicile=None):
    """domicile=True : seulement les matchs a domicile. False : seulement a l'exterieur.
    None : tous les matchs, peu importe le lieu."""
    date_fin = datetime.date.today()
    date_debut = date_fin - datetime.timedelta(days=200)
    r = requests.get(
        f"{API_URL}/teams/{team_id}/matches",
        headers=HEADERS,
        params={
            "status": "FINISHED",
            "dateFrom": date_debut.isoformat(),
            "dateTo": date_fin.isoformat(),
        },
        timeout=10,
    )
    j = r.json()
    tous_les_matchs = j.get("matches", [])
    tous_les_matchs.sort(key=lambda m: m["utcDate"], reverse=True)

    if domicile is True:
        matchs = [m for m in tous_les_matchs if m["homeTeam"]["id"] == team_id][:10]
    elif domicile is False:
        matchs = [m for m in tous_les_matchs if m["awayTeam"]["id"] == team_id][:10]
    else:
        matchs = tous_les_matchs[:10]

    # Pas assez de matchs a domicile/exterieur ? On retombe sur l'ensemble des matchs.
    if domicile is not None and len(matchs) < 3:
        matchs = tous_les_matchs[:10]

    DECAY = 0.85  # les matchs les plus recents comptent plus (matchs[0] = le plus recent)
    bm_pond, be_pond, poids_total, n = 0.0, 0.0, 0.0, 0
    for i, m in enumerate(matchs):
        home_id = m["homeTeam"]["id"]
        gh = m["score"]["fullTime"]["home"]
        ga = m["score"]["fullTime"]["away"]
        if gh is None or ga is None:
            continue
        bm, be = (gh, ga) if home_id == team_id else (ga, gh)
        poids = DECAY ** i
        bm_pond += bm * poids
        be_pond += be * poids
        poids_total += poids
        n += 1

    if n == 0:
        return LIGUE_MOYENNE, LIGUE_MOYENNE, 0
    return bm_pond / poids_total, be_pond / poids_total, n


def calcul_pronostic(buts_a, enc_a, buts_b, enc_b, ligue=LIGUE_MOYENNE):
    lam_a = max(0.1, (buts_a / ligue) * (enc_b / ligue) * ligue)
    lam_b = max(0.1, (buts_b / ligue) * (enc_a / ligue) * ligue)

    p_win = p_draw = p_lose = 0.0
    best = (0.0, 0, 0)
    MAX_BUTS = 7
    for x in range(MAX_BUTS + 1):
        for y in range(MAX_BUTS + 1):
            p = poisson(lam_a, x) * poisson(lam_b, y)
            if x > y:
                p_win += p
            elif x == y:
                p_draw += p
            else:
                p_lose += p
            if p > best[0]:
                best = (p, x, y)

    total = p_win + p_draw + p_lose
    return p_win / total, p_draw / total, p_lose / total, best, lam_a, lam_b


def calc_btts(lam_a, lam_b):
    """Probabilite que les deux equipes marquent au moins 1 but chacune."""
    p_a_marque = 1 - poisson(lam_a, 0)
    p_b_marque = 1 - poisson(lam_b, 0)
    return p_a_marque * p_b_marque


def calc_confiance(n_a, n_b, p_win, p_draw, p_lose):
    """Retourne un score de confiance de 1 a 5 etoiles."""
    probs = sorted([p_win, p_draw, p_lose], reverse=True)
    ecart = probs[0] - probs[1]  # plus l'ecart est grand, plus un resultat se detache

    points = 0.0
    points += min(n_a, n_b) / 10 * 2       # jusqu'a 2 points selon le nombre de matchs analyses
    points += min(ecart * 6, 3)            # jusqu'a 3 points selon la clarte du favori

    etoiles_pleines = max(1, min(5, round(points)))
    return "⭐" * etoiles_pleines + "☆" * (5 - etoiles_pleines)


def barre(pct, taille=10):
    plein = round(pct * taille)
    return "█" * plein + "░" * (taille - plein)


def ticket(nom_a, nom_b, p_win, p_draw, p_lose, best, n_a, n_b, p_btts, confiance,
           emoji="⚽", label_nul="Nul"):
    return (
        "```\n"
        "╔═══════════════════════╗\n"
        "   🎫 TICKET PRONOSTIC\n"
        "╚═══════════════════════╝\n\n"
        f" {emoji} {nom_a} 🆚 {nom_b}\n\n"
        f" {nom_a[:12]:<12} {barre(p_win)} {p_win*100:>3.0f}%\n"
        f" {label_nul[:12]:<12} {barre(p_draw)} {p_draw*100:>3.0f}%\n"
        f" {nom_b[:12]:<12} {barre(p_lose)} {p_lose*100:>3.0f}%\n\n"
        f" Score probable : {best[1]} - {best[2]}\n"
        f" Les 2 équipes marquent : {p_btts*100:.0f}%\n"
        f" Confiance : {confiance}\n"
        "───────────────────────────\n"
        f" (matchs analysés : {n_a} / {n_b})\n"
        " ⚠️ Estimation statistique,\n"
        "    pas une certitude.\n"
        "```"
    )


SEPARATEUR = re.compile(r"\s+(?:vs|versus|contre)\s+", re.IGNORECASE)


async def predict(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not est_autorise(update.effective_chat.id):
        await update.message.reply_text("⛔ Ce bot est privé.")
        return

    texte = " ".join(context.args).strip()
    morceaux = SEPARATEUR.split(texte, maxsplit=1)

    if len(morceaux) != 2 or not morceaux[0].strip() or not morceaux[1].strip():
        await update.message.reply_text(
            "Format : /predict Equipe A vs Equipe B\n"
            "(vs, versus ou contre fonctionnent)\n"
            "Exemple : /predict PSG vs Marseille"
        )
        return

    nom_a_in, nom_b_in = morceaux[0].strip(), morceaux[1].strip()

    await update.message.reply_text("🔎 Recherche des équipes et des stats...")

    try:
        id_a, nom_a = trouver_equipe(nom_a_in)
        id_b, nom_b = trouver_equipe(nom_b_in)
        if not id_a or not id_b:
            await update.message.reply_text(
                "Équipe non reconnue. Essaie un grand club européen "
                "(PSG, Marseille, Real Madrid, Barcelone, Bayern, Man City...)."
            )
            return

        buts_a, enc_a, n_a = stats_equipe(id_a, domicile=True)
        buts_b, enc_b, n_b = stats_equipe(id_b, domicile=False)

        p_win, p_draw, p_lose, best, lam_a, lam_b = calcul_pronostic(buts_a, enc_a, buts_b, enc_b)
        p_btts = calc_btts(lam_a, lam_b)
        confiance = calc_confiance(n_a, n_b, p_win, p_draw, p_lose)
        enregistrer_pronostic("foot", nom_a, nom_b, id_a, id_b, p_win, p_draw, p_lose, best)
        await update.message.reply_text(
            ticket(nom_a, nom_b, p_win, p_draw, p_lose, best, n_a, n_b, p_btts, confiance),
            parse_mode="Markdown",
        )
    except Exception as e:
        await update.message.reply_text(f"Erreur : {e}")


async def hockey(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not est_autorise(update.effective_chat.id):
        await update.message.reply_text("⛔ Ce bot est privé.")
        return

    texte = " ".join(context.args).strip()
    morceaux = SEPARATEUR.split(texte, maxsplit=1)

    if len(morceaux) != 2 or not morceaux[0].strip() or not morceaux[1].strip():
        await update.message.reply_text(
            "Format : /hockey Equipe A vs Equipe B\n"
            "(vs, versus ou contre fonctionnent)\n"
            "Exemple : /hockey Boston vs Toronto"
        )
        return

    nom_a_in, nom_b_in = morceaux[0].strip(), morceaux[1].strip()
    await update.message.reply_text("🔎 Recherche des équipes et des stats NHL...")

    try:
        code_a, nom_a = trouver_equipe_nhl(nom_a_in)
        code_b, nom_b = trouver_equipe_nhl(nom_b_in)
        if not code_a or not code_b:
            await update.message.reply_text(
                "Équipe NHL non reconnue. Essaie le nom de la ville ou du club "
                "(Boston, Bruins, Toronto, Maple Leafs...)."
            )
            return

        buts_a, enc_a, n_a = stats_equipe_nhl(code_a, domicile=True)
        buts_b, enc_b, n_b = stats_equipe_nhl(code_b, domicile=False)

        p_win, p_draw, p_lose, best, lam_a, lam_b = calcul_pronostic(
            buts_a, enc_a, buts_b, enc_b, ligue=LIGUE_MOYENNE_NHL
        )
        p_btts = calc_btts(lam_a, lam_b)
        confiance = calc_confiance(n_a, n_b, p_win, p_draw, p_lose)
        enregistrer_pronostic("hockey", nom_a, nom_b, code_a, code_b, p_win, p_draw, p_lose, best)
        await update.message.reply_text(
            ticket(
                nom_a, nom_b, p_win, p_draw, p_lose, best, n_a, n_b, p_btts, confiance,
                emoji="🏒", label_nul="Nul (60 min)",
            ),
            parse_mode="Markdown",
        )
    except Exception as e:
        await update.message.reply_text(f"Erreur : {e}")


def tg_envoyer(chat_id, texte, markdown=False):
    """Envoie un message Telegram directement par HTTP, sans dependre de la file d'attente
    interne du bot (donc fiable meme declenche depuis une route web externe)."""
    try:
        data = {"chat_id": chat_id, "text": texte}
        if markdown:
            data["parse_mode"] = "Markdown"
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json=data, timeout=15
        )
    except Exception:
        pass


def pronostics_jour(chat_id):
    date_du_jour = datetime.date.today().isoformat()
    matchs = None
    for tentative in range(3):
        try:
            r = requests.get(
                f"{API_URL}/matches",
                headers=HEADERS,
                params={
                    "dateFrom": date_du_jour,
                    "dateTo": date_du_jour,
                    "competitions": ",".join(COMPETITIONS),
                },
                timeout=20,
            )
            tous = r.json().get("matches", [])
            print(f"DEBUG pronostics_jour: {len(tous)} matchs bruts recus, statuts: {[m['status'] for m in tous]}")
            matchs = [m for m in tous if m["status"] in ("SCHEDULED", "TIMED")]
            break
        except Exception as e:
            print(f"DEBUG pronostics_jour erreur: {e}")
            time.sleep(5)

    if matchs is None:
        tg_envoyer(chat_id, "⚠️ L'API de football ne répond pas pour l'instant, réessaie avec /predict un peu plus tard.")
        return

    if not matchs:
        tg_envoyer(chat_id, "🌞 Bonjour ! Aucun match majeur aujourd'hui.")
        return

    tg_envoyer(chat_id, f"🌞 Bonjour ! Pronostics du jour ({len(matchs)} match{'s' if len(matchs) > 1 else ''}) :")
    for m in matchs[:12]:
        nom_a, id_a = m["homeTeam"]["name"], m["homeTeam"]["id"]
        nom_b, id_b = m["awayTeam"]["name"], m["awayTeam"]["id"]
        try:
            buts_a, enc_a, n_a = stats_equipe(id_a, domicile=True)
            buts_b, enc_b, n_b = stats_equipe(id_b, domicile=False)
            p_win, p_draw, p_lose, best, lam_a, lam_b = calcul_pronostic(buts_a, enc_a, buts_b, enc_b)
            p_btts = calc_btts(lam_a, lam_b)
            enregistrer_pronostic("foot", nom_a, nom_b, id_a, id_b, p_win, p_draw, p_lose, best)
            confiance = calc_confiance(n_a, n_b, p_win, p_draw, p_lose)
            tg_envoyer(
                chat_id,
                ticket(nom_a, nom_b, p_win, p_draw, p_lose, best, n_a, n_b, p_btts, confiance),
                markdown=True,
            )
        except Exception:
            pass
        time.sleep(2)


def pronostics_jour_hockey(chat_id):
    date_du_jour = datetime.date.today().isoformat()

    matchs = None
    for tentative in range(3):
        try:
            r = requests.get(f"{NHL_URL}/schedule/{date_du_jour}", timeout=20)
            data = r.json()
            jour = next(
                (j for j in data.get("gameWeek", []) if j.get("date") == date_du_jour), None
            )
            matchs = [
                m for m in (jour.get("games", []) if jour else [])
                if m.get("gameState") in ("FUT", "PRE")
            ]
            break
        except Exception:
            time.sleep(5)

    if matchs is None:
        tg_envoyer(chat_id, "⚠️ L'API NHL ne répond pas pour l'instant, réessaie avec /hockey un peu plus tard.")
        return

    if not matchs:
        tg_envoyer(chat_id, "🏒 Aucun match NHL aujourd'hui.")
        return

    tg_envoyer(chat_id, f"🏒 Pronostics hockey du jour ({len(matchs)} match{'s' if len(matchs) > 1 else ''}) :")
    for m in matchs[:12]:
        try:
            code_a = m["homeTeam"]["abbrev"]
            code_b = m["awayTeam"]["abbrev"]
            nom_a = m["homeTeam"].get("placeName", {}).get("default", code_a)
            nom_b = m["awayTeam"].get("placeName", {}).get("default", code_b)

            buts_a, enc_a, n_a = stats_equipe_nhl(code_a, domicile=True)
            buts_b, enc_b, n_b = stats_equipe_nhl(code_b, domicile=False)
            p_win, p_draw, p_lose, best, lam_a, lam_b = calcul_pronostic(
                buts_a, enc_a, buts_b, enc_b, ligue=LIGUE_MOYENNE_NHL
            )
            p_btts = calc_btts(lam_a, lam_b)
            confiance = calc_confiance(n_a, n_b, p_win, p_draw, p_lose)
            enregistrer_pronostic("hockey", nom_a, nom_b, code_a, code_b, p_win, p_draw, p_lose, best)
            tg_envoyer(
                chat_id,
                ticket(
                    nom_a, nom_b, p_win, p_draw, p_lose, best, n_a, n_b, p_btts, confiance,
                    emoji="🏒", label_nul="Nul (60 min)",
                ),
                markdown=True,
            )
        except Exception:
            pass
        time.sleep(2)


def verifier_pronostics():
    """Verifie les pronostics vieux de 3 jours ou plus, en cherchant le vrai resultat."""
    if not SUPABASE_URL:
        return
    try:
        limite = (datetime.date.today() - datetime.timedelta(days=3)).isoformat()
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/pronostics",
            headers=sb_headers(),
            params={
                "verifie": "eq.false",
                "date_creation": f"lt.{limite}",
                "select": "*",
                "limit": "50",
            },
            timeout=15,
        )
        a_verifier = r.json()
    except Exception:
        return

    for p in a_verifier:
        try:
            resultat_reel = None
            if p["sport"] == "foot":
                id_a, id_b = int(p["id_a"]), int(p["id_b"])
                rr = requests.get(
                    f"{API_URL}/teams/{id_a}/matches",
                    headers=HEADERS,
                    params={
                        "status": "FINISHED",
                        "dateFrom": p["date_creation"][:10],
                        "dateTo": datetime.date.today().isoformat(),
                    },
                    timeout=15,
                )
                for m in rr.json().get("matches", []):
                    if m["homeTeam"]["id"] == id_a and m["awayTeam"]["id"] == id_b:
                        gh, ga = m["score"]["fullTime"]["home"], m["score"]["fullTime"]["away"]
                        if gh is not None and ga is not None:
                            resultat_reel = "victoire_a" if gh > ga else ("nul" if gh == ga else "victoire_b")
                        break
            else:  # hockey
                code_a, code_b = p["id_a"], p["id_b"]
                rr = requests.get(f"{NHL_URL}/club-schedule-season/{code_a}/{saison_nhl()}", timeout=15)
                for m in rr.json().get("games", []):
                    if (
                        m.get("gameState") == "OFF"
                        and m["homeTeam"]["abbrev"] == code_a
                        and m["awayTeam"]["abbrev"] == code_b
                        and m.get("gameDate", "") >= p["date_creation"][:10]
                    ):
                        gh, ga = m["homeTeam"]["score"], m["awayTeam"]["score"]
                        resultat_reel = "victoire_a" if gh > ga else ("nul" if gh == ga else "victoire_b")
                        break

            if resultat_reel is None:
                continue  # match pas encore joue ou pas trouve, on reessaiera plus tard

            predit = label_resultat(p["p_win"], p["p_draw"], p["p_lose"])
            requests.patch(
                f"{SUPABASE_URL}/rest/v1/pronostics",
                headers={**sb_headers(), "Prefer": "return=minimal"},
                params={"id": f"eq.{p['id']}"},
                json={
                    "resultat_reel": resultat_reel,
                    "correct": predit == resultat_reel,
                    "verifie": True,
                },
                timeout=10,
            )
        except Exception:
            continue


async def fiabilite(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not est_autorise(update.effective_chat.id):
        await update.message.reply_text("⛔ Ce bot est privé.")
        return
    if not SUPABASE_URL:
        await update.message.reply_text("La base de données n'est pas configurée.")
        return

    try:
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/pronostics",
            headers=sb_headers(),
            params={"verifie": "eq.true", "select": "correct,sport"},
            timeout=15,
        )
        lignes = r.json()
    except Exception as e:
        await update.message.reply_text(f"Erreur : {e}")
        return

    if not lignes:
        await update.message.reply_text(
            "Pas encore assez de pronostics vérifiés (il faut attendre que les matchs aient eu lieu)."
        )
        return

    total = len(lignes)
    corrects = sum(1 for l in lignes if l["correct"])
    foot = [l for l in lignes if l["sport"] == "foot"]
    hockey_l = [l for l in lignes if l["sport"] == "hockey"]

    def pct(liste):
        if not liste:
            return "N/A"
        return f"{sum(1 for l in liste if l['correct']) / len(liste) * 100:.0f}%"

    await update.message.reply_text(
        "📊 Fiabilité du bot\n\n"
        f"Global : {corrects}/{total} ({corrects/total*100:.0f}%)\n"
        f"⚽ Foot : {pct(foot)} ({len(foot)} pronostics)\n"
        f"🏒 Hockey : {pct(hockey_l)} ({len(hockey_l)} pronostics)"
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not est_autorise(chat_id):
        await update.message.reply_text("⛔ Ce bot est privé.")
        return

    heure_foot = HEURE_ENVOI.strftime("%Hh%M")
    heure_hockey = HEURE_ENVOI_HOCKEY.strftime("%Hh%M")
    await update.message.reply_text(
        "⚽ Salut ! Utilise /predict Equipe A vs Equipe B\n"
        "(vs, versus ou contre fonctionnent)\n"
        "Exemple : /predict PSG vs Marseille\n\n"
        "🏒 Pour le hockey (NHL) : /hockey Equipe A vs Equipe B\n"
        "Exemple : /hockey Boston vs Toronto\n\n"
        f"📅 Foot : pronostics automatiques chaque jour à {heure_foot}.\n"
        f"📅 Hockey : pronostics automatiques chaque jour à {heure_hockey}.\n\n"
        "📊 Utilise /fiabilite pour voir le taux de réussite réel du bot."
    )


if __name__ == "__main__":
    threading.Thread(target=lancer_serveur_web, daemon=True).start()

    charger_equipes()
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("predict", predict))
    app.add_handler(CommandHandler("hockey", hockey))
    app.add_handler(CommandHandler("fiabilite", fiabilite))

    print("Bot lance...")
    app.run_polling()
