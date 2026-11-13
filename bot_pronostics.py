import os
import re
import math
import time
import asyncio
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

API_URL = "https://api.football-data.org/v4"
HEADERS = {"X-Auth-Token": FOOTBALL_TOKEN}
LIGUE_MOYENNE = 1.4
CHAT_ID_FILE = "chat_id.txt"
HEURE_ENVOI = datetime.time(hour=9, minute=0, tzinfo=ZoneInfo("Africa/Abidjan"))

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

    buts_marques, buts_encaisses, n = 0, 0, 0
    for m in matchs:
        est_domicile = m["homeTeam"]["abbrev"] == tricode
        bm = m["homeTeam"]["score"] if est_domicile else m["awayTeam"]["score"]
        be = m["awayTeam"]["score"] if est_domicile else m["homeTeam"]["score"]
        buts_marques += bm
        buts_encaisses += be
        n += 1

    if n == 0:
        return LIGUE_MOYENNE_NHL, LIGUE_MOYENNE_NHL, 0
    return buts_marques / n, buts_encaisses / n, n


# ---------- Mini serveur web, juste pour qu'UptimeRobot ait quelque chose a "pinger" ----------
web = Flask(__name__)


@web.route("/")
def accueil():
    return "Bot de pronostics en ligne."


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

    buts_marques, buts_encaisses, n = 0, 0, 0
    for m in matchs:
        home_id = m["homeTeam"]["id"]
        gh = m["score"]["fullTime"]["home"]
        ga = m["score"]["fullTime"]["away"]
        if gh is None or ga is None:
            continue
        if home_id == team_id:
            buts_marques += gh
            buts_encaisses += ga
        else:
            buts_marques += ga
            buts_encaisses += gh
        n += 1

    if n == 0:
        return LIGUE_MOYENNE, LIGUE_MOYENNE, 0
    return buts_marques / n, buts_encaisses / n, n


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
        await update.message.reply_text(
            ticket(nom_a, nom_b, p_win, p_draw, p_lose, best, n_a, n_b, p_btts, confiance),
            parse_mode="Markdown",
        )
    except Exception as e:
        await update.message.reply_text(f"Erreur : {e}")


async def hockey(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        await update.message.reply_text(
            ticket(
                nom_a, nom_b, p_win, p_draw, p_lose, best, n_a, n_b, p_btts, confiance,
                emoji="🏒", label_nul="Nul (60 min)",
            ),
            parse_mode="Markdown",
        )
    except Exception as e:
        await update.message.reply_text(f"Erreur : {e}")


async def pronostics_jour(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.chat_id
    date_du_jour = datetime.date.today().isoformat()
    matchs = None
    for tentative in range(3):
        try:
            r = requests.get(
                f"{API_URL}/matches",
                headers=HEADERS,
                params={"dateFrom": date_du_jour, "dateTo": date_du_jour},
                timeout=20,
            )
            matchs = [
                m for m in r.json().get("matches", [])
                if m["status"] in ("SCHEDULED", "TIMED")
            ]
            break
        except Exception:
            await asyncio.sleep(5)

    if matchs is None:
        await context.bot.send_message(
            chat_id, "⚠️ L'API de football ne répond pas pour l'instant, réessaie avec /predict un peu plus tard."
        )
        return

    if not matchs:
        await context.bot.send_message(chat_id, "🌞 Bonjour ! Aucun match majeur aujourd'hui.")
        return

    await context.bot.send_message(
        chat_id, f"🌞 Bonjour ! Pronostics du jour ({len(matchs)} match{'s' if len(matchs) > 1 else ''}) :"
    )
    for m in matchs[:12]:
        nom_a, id_a = m["homeTeam"]["name"], m["homeTeam"]["id"]
        nom_b, id_b = m["awayTeam"]["name"], m["awayTeam"]["id"]
        try:
            buts_a, enc_a, n_a = stats_equipe(id_a, domicile=True)
            buts_b, enc_b, n_b = stats_equipe(id_b, domicile=False)
            p_win, p_draw, p_lose, best, lam_a, lam_b = calcul_pronostic(buts_a, enc_a, buts_b, enc_b)
            p_btts = calc_btts(lam_a, lam_b)
            confiance = calc_confiance(n_a, n_b, p_win, p_draw, p_lose)
            await context.bot.send_message(
                chat_id,
                ticket(nom_a, nom_b, p_win, p_draw, p_lose, best, n_a, n_b, p_btts, confiance),
                parse_mode="Markdown",
            )
        except Exception:
            pass
        await asyncio.sleep(2)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    with open(CHAT_ID_FILE, "w") as f:
        f.write(str(chat_id))

    for job in context.job_queue.get_jobs_by_name("pronostics_jour"):
        job.schedule_removal()
    context.job_queue.run_daily(
        pronostics_jour, time=HEURE_ENVOI, chat_id=chat_id, name="pronostics_jour"
    )

    heure_txt = HEURE_ENVOI.strftime("%Hh%M")
    await update.message.reply_text(
        "⚽ Salut ! Utilise /predict Equipe A vs Equipe B\n"
        "(vs, versus ou contre fonctionnent)\n"
        "Exemple : /predict PSG vs Marseille\n\n"
        "🏒 Pour le hockey (NHL) : /hockey Equipe A vs Equipe B\n"
        "Exemple : /hockey Boston vs Toronto\n\n"
        f"📅 Tu recevras aussi automatiquement les pronostics du jour chaque matin à {heure_txt}."
    )


if __name__ == "__main__":
    threading.Thread(target=lancer_serveur_web, daemon=True).start()

    charger_equipes()
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("predict", predict))
    app.add_handler(CommandHandler("hockey", hockey))

    try:
        with open(CHAT_ID_FILE) as f:
            chat_id_sauve = int(f.read().strip())
        app.job_queue.run_daily(
            pronostics_jour, time=HEURE_ENVOI, chat_id=chat_id_sauve, name="pronostics_jour"
        )
        print(f"Envoi quotidien programme pour le chat {chat_id_sauve}")
    except FileNotFoundError:
        pass

    print("Bot lance...")
    app.run_polling()
