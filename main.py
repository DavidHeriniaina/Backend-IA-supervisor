from dotenv import load_dotenv
import os
import sys
import json
import base64
import firebase_admin
from firebase_admin import credentials, firestore
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

load_dotenv()

app = FastAPI(
    title="Backend IA Superviseur",
    description="Microservice IA pour la génération intelligente de questionnaires d'audit et recommandations stratégiques",
    version="2.0.0"
)

# Middleware pour restaurer le chemin d'URL sous Vercel Serverless
from starlette.types import ASGIApp, Receive, Scope, Send

class VercelPathMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] == "http":
            headers = dict(scope.get("headers", []))
            for header_name in [
                b"x-matched-path",
                b"x-forwarded-uri",
                b"x-original-url",
                b"x-rewrite-url",
                b"x-invoke-path",
                b"x-real-path",
                b"x-vercel-path"
            ]:
                val = headers.get(header_name)
                if val:
                    try:
                        raw = val.decode("utf-8").split("?")[0]
                        if raw and raw not in ["/main.py", "/index.py", "/api/index.py"]:
                            scope["path"] = raw
                            break
                    except Exception:
                        pass
        await self.app(scope, receive, send)

app.add_middleware(VercelPathMiddleware)

# Activer CORS pour permettre les appels depuis le Frontend Web et Flutter
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==================== INITIALISATION GEMINI AI ====================
gemini_client = None
gemini_error = None
gemini_api_key = os.environ.get("GEMINI_API_KEY")

if gemini_api_key:
    try:
        from google import genai
        gemini_client = genai.Client(api_key=gemini_api_key)
        print("✅ Gemini AI initialisé avec succès")
    except Exception as e:
        gemini_error = str(e)
        print(f"⚠️ Erreur initialisation Gemini : {e}")
else:
    gemini_error = "GEMINI_API_KEY non configurée"
    print("⚠️ GEMINI_API_KEY non configurée dans l'environnement")

# ==================== INITIALISATION FIREBASE ====================
db = None
firebase_error = None

def init_firebase():
    global db, firebase_error
    if db is not None:
        return db

    if firebase_admin._apps:
        db = firestore.client()
        return db

    firebase_credentials = None

    sa_json = os.environ.get("FIREBASE_SA_JSON")
    if sa_json:
        try:
            if sa_json.startswith("ey"):  # Base64 pattern
                sa_json = base64.b64decode(sa_json).decode("utf-8")
            firebase_credentials = json.loads(sa_json)
        except Exception as e:
            print(f"⚠️ Erreur parsing FIREBASE_SA_JSON : {e}")

    if not firebase_credentials:
        key_path = os.environ.get("FIREBASE_CREDENTIALS_PATH", "./firebase-key.json")
        if os.path.exists(key_path):
            try:
                with open(key_path, "r", encoding="utf-8") as f:
                    firebase_credentials = json.load(f)
            except Exception as e:
                print(f"⚠️ Erreur lecture fichier clé : {e}")

    if firebase_credentials:
        try:
            cred = credentials.Certificate(firebase_credentials)
            firebase_admin.initialize_app(cred)
            db = firestore.client()
            print("✅ Firebase initialisé avec succès")
        except Exception as e:
            firebase_error = str(e)
            print(f"⚠️ Erreur init Firebase Admin : {e}")
    else:
        firebase_error = "Aucune clé Firebase trouvée"

    return db

try:
    init_firebase()
except Exception as e:
    firebase_error = str(e)


# ==================== MOTEUR DE GÉNÉRATION INTELLIGENTE ====================

def generer_questions_fallback(payload: dict) -> dict:
    """Générateur déterministe de secours selon les données de la mission."""
    marque = payload.get("marque", "Marque")
    rayon = payload.get("rayon", "Linéaire")
    magasin = payload.get("magasin", "Point de Vente")
    consignes = payload.get("consignes", "")
    familles = payload.get("familles", ["Gamme Principale"])
    produits = payload.get("produits", [])

    questions = []
    q_num = 1

    # NIVEAU 1 : LINÉAIRE & RAYON GLOBAL
    questions.extend([
        {
            "id": f"q{q_num}_proprete",
            "label": f"{q_num}. Le linéaire {rayon} est-il propre et correctement tenu ?",
            "type": "oui_non",
            "required": True,
            "options": []
        },
        {
            "id": f"q{q_num+1}_planogramme",
            "label": f"{q_num+1}. Le planogramme {marque} est-il respecté ?",
            "type": "oui_non",
            "required": True,
            "options": []
        },
        {
            "id": f"q{q_num+2}_balisage",
            "label": f"{q_num+2}. Le balisage prix {marque} est-il présent et lisible ?",
            "type": "oui_non",
            "required": True,
            "options": []
        },
        {
            "id": f"q{q_num+3}_gondole",
            "label": f"{q_num+3}. La marque {marque} est-elle visible en tête de gondole ou zone promo ?",
            "type": "oui_non",
            "required": True,
            "options": []
        },
        {
            "id": f"q{q_num+4}_assortiment",
            "label": f"{q_num+4}. L'assortiment global {rayon} correspond-il aux accords commerciaux ?",
            "type": "oui_non",
            "required": True,
            "options": []
        },
        {
            "id": f"q{q_num+5}_photo",
            "label": f"{q_num+5}. Photo panoramique d’ensemble du linéaire {marque}",
            "type": "photo",
            "required": True,
            "options": []
        },
        {
            "id": f"q{q_num+6}_note",
            "label": f"{q_num+6}. Note globale de visibilité et d’impact visuel du linéaire (1 à 5)",
            "type": "note",
            "required": True,
            "options": []
        }
    ])
    q_num += 7

    # NIVEAU 2 : PAR FAMILLE DE PRODUITS
    for fam in familles:
        fam_prods = [
            p for p in produits 
            if isinstance(p, dict) and fam.lower() in (p.get("categorie") or p.get("famille") or "").lower()
        ]
        
        prod_names = [p.get("nom") or p.get("titre") for p in fam_prods if p.get("nom") or p.get("titre")]
        
        # Formater les cibles prix
        price_targets = [
            f"{p.get('nom') or 'Produit'} = {p.get('prix_conseille') or p.get('prix')} Ar"
            for p in fam_prods if p.get("prix_conseille") or p.get("prix")
        ]
        price_suffix = f" (Vérifier : {' ; '.join(price_targets)})" if price_targets else ""

        # Formater la cible facing
        facing_target = next((p.get("facing_cible") or p.get("facing") for p in fam_prods if p.get("facing_cible") or p.get("facing")), None)
        facing_suffix = f" (Cible : {facing_target})" if facing_target else ""

        clean_fam = fam.replace(" ", "_").lower()
        questions.extend([
            {
                "id": f"q{q_num}_fam_{clean_fam}_presence",
                "label": f"{q_num}. [Famille {fam}] Toutes les références {marque} sont-elles présentes ?",
                "type": "choix_multiple",
                "required": True,
                "options": ["Toutes (100% présentes)", "Partiellement (1 ou 2 manquantes)", "Aucune (Rupture totale)"]
            },
            {
                "id": f"q{q_num+1}_fam_{clean_fam}_manquantes",
                "label": f"{q_num+1}. [Famille {fam}] Si non, quelles références sont manquantes ? (Checklist MDM)",
                "type": "choix_multiple",
                "required": False,
                "options": prod_names if prod_names else ["Référence 1", "Référence 2"]
            },
            {
                "id": f"q{q_num+2}_fam_{clean_fam}_rupture",
                "label": f"{q_num+2}. [Famille {fam}] Une rupture de stock est-elle constatée ?",
                "type": "choix_multiple",
                "required": True,
                "options": ["Aucune", "1 référence", "2 références ou plus"]
            },
            {
                "id": f"q{q_num+3}_fam_{clean_fam}_prix",
                "label": f"{q_num+3}. [Famille {fam}] Le prix affiché est-il conforme au tarif conseillé ou promo ?{price_suffix}",
                "type": "choix_multiple",
                "required": True,
                "options": ["Conforme", "Écart de prix constaté (surprix)", "Promotion non appliquée"]
            },
            {
                "id": f"q{q_num+4}_fam_{clean_fam}_facing",
                "label": f"{q_num+4}. [Famille {fam}] Le facing visible est-il suffisant ?{facing_suffix}",
                "type": "choix_multiple",
                "required": True,
                "options": ["Suffisant (Conforme)", "Insuffisant (Sous-facing)"]
            },
            {
                "id": f"q{q_num+5}_fam_{clean_fam}_promo",
                "label": f"{q_num+5}. [Famille {fam}] Une opération promotionnelle est-elle visible en rayon ?",
                "type": "oui_non",
                "required": True,
                "options": []
            }
        ])
        q_num += 6

    return {
        "status": "ok",
        "source": "heuristic_engine",
        "titre": f"Audit Hybride - {magasin} ({marque})",
        "description": consignes or f"Audit de conformité linéaire pour {marque} à {magasin}.",
        "questions": questions,
        "count": len(questions)
    }


async def generer_questions_gemini(payload: dict) -> dict:
    """Génération par IA Gemini à partir du prompt/brief et des données de la mission."""
    if not gemini_client:
        return generer_questions_fallback(payload)

    marque = payload.get("marque", "Marque")
    rayon = payload.get("rayon", "Linéaire")
    magasin = payload.get("magasin", "Point de Vente")
    consignes = payload.get("consignes", "Vérifier la visibilité, les prix et les facings.")
    familles = payload.get("familles", ["Gamme Principale"])
    produits = payload.get("produits", [])

    system_prompt = (
        "Tu es un expert en Trade Marketing, Merchandising Retail et Supervision de Réseaux de Distribution. "
        "Ton rôle est de concevoir une fiche d'audit terrain ultra-précise et adaptée pour les enquêteurs mobiles in situ.\n\n"
        "STRUCTURE DU QUESTIONNAIRE :\n"
        "1. Niveau 1 (Linéaire / Rayon global) : Questions d'ambiance, propreté, planogramme, balisage, tête de gondole/zone promo, photo panoramique, note 1-5.\n"
        "2. Niveau 2 (Par Famille de produits ciblée) : Pour chaque famille ciblée, génère le bloc de contrôle standardisé (Présence globale, Checklist références manquantes, Rupture constatée, Conformité Prix conseillés/promo, Facing suffisant vs Cible, Animation promotionnelle).\n"
        "3. Inclus explicitement dans les libellés les cibles de prix conseillés et de facing fournies dans la liste des produits.\n"
        "4. Prends en compte toutes les consignes spécifiques du brief (ex: tête de gondole, concurrence, promo).\n\n"
        "FORMAT DE RÉPONSE OBLIGATOIRE :\n"
        "Renvoie UNIQUEMENT un objet JSON valide avec cette structure sans texte superflu :\n"
        "{\n"
        "  \"titre\": \"Titre de la fiche\",\n"
        "  \"description\": \"Description de la mission\",\n"
        "  \"questions\": [\n"
        "    {\n"
        "      \"id\": \"q1_id_unique\",\n"
        "      \"label\": \"1. Intitulé complet de la question\",\n"
        "      \"type\": \"oui_non\" | \"choix_multiple\" | \"photo\" | \"note\" | \"texte\" | \"nombre\",\n"
        "      \"required\": true,\n"
        "      \"options\": [\"Option 1\", \"Option 2\"] (si choix_multiple, sinon tableau vide)\n"
        "    }\n"
        "  ]\n"
        "}"
    )

    user_context = (
        f"CONTEXTE DE LA MISSION :\n"
        f"- Point de vente : {magasin}\n"
        f"- Marque commanditaire : {marque}\n"
        f"- Rayon / Secteur : {rayon}\n"
        f"- Consignes & Objectifs du Fournisseur : \"{consignes}\"\n"
        f"- Familles ciblées : {json.dumps(familles, ensure_ascii=False)}\n"
        f"- Produits MDM du panier : {json.dumps(produits, ensure_ascii=False)}\n"
    )

    model_names = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]
    for model_name in model_names:
        try:
            response = gemini_client.models.generate_content(
                model=model_name,
                contents=f"{system_prompt}\n\n{user_context}"
            )
            if response and response.text:
                raw_text = response.text.strip()
                if "```json" in raw_text:
                    raw_text = raw_text.split("```json")[1].split("```")[0].strip()
                elif "```" in raw_text:
                    raw_text = raw_text.split("```")[1].split("```")[0].strip()

                parsed = json.loads(raw_text)
                if "questions" in parsed and isinstance(parsed["questions"], list) and len(parsed["questions"]) > 0:
                    return {
                        "status": "ok",
                        "source": f"gemini_{model_name}",
                        "titre": parsed.get("titre", f"Audit - {magasin} ({marque})"),
                        "description": parsed.get("description", consignes),
                        "questions": parsed["questions"],
                        "count": len(parsed["questions"])
                    }
        except Exception as e:
            print(f"⚠️ Erreur génération Gemini ({model_name}) : {e}")
            continue

    return generer_questions_fallback(payload)


async def obtenir_conseil_strategique_gemini(payload: dict) -> list:
    """Génération des 3 recommandations stratégiques exécutives."""
    brand = payload.get("brand_name", "Chocolaterie Robert")
    ruptures = payload.get("top_ruptures", [])
    cat_stats = payload.get("categories_stats", {})
    enseignes = payload.get("enseignes_stats", {})
    regions = payload.get("regions_stats", {})

    prompt = (
        f"Tu es un directeur commercial et logistique expert en Retail à Madagascar pour la marque {brand}. "
        f"Voici les données d'audit consolidées du réseau de distribution :\n"
        f"- Ruptures critiques constatées : {json.dumps(ruptures, ensure_ascii=False)}\n"
        f"- Performances par catégorie : {json.dumps(cat_stats, ensure_ascii=False)}\n"
        f"- Performances par enseigne : {json.dumps(enseignes, ensure_ascii=False)}\n"
        f"- Performances régionales : {json.dumps(regions, ensure_ascii=False)}\n\n"
        "Génère exactement 3 recommandations stratégiques exécutives, concrètes et immédiatement actionnables "
        "numérotées 1, 2 et 3 :\n"
        "1. Recommandation Disponibilité & Visibilité Linéaire (focus zones ou produits en rupture)\n"
        "2. Recommandation Négociation Enseignes (focus facing, litiges ou pénalités de sous-performance)\n"
        "3. Recommandation Commerciale & Allocation Budgétaire (arbitrage des tournées et audit)"
    )

    if gemini_client:
        model_names = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]
        for model_name in model_names:
            try:
                response = gemini_client.models.generate_content(
                    model=model_name,
                    contents=prompt
                )
                if response and response.text:
                    lines = [line.strip() for line in response.text.split("\n") if line.strip()]
                    return lines if len(lines) >= 3 else [response.text.strip()]
            except Exception as e:
                print(f"⚠️ Erreur Gemini Strategic Advice ({model_name}): {e}")
                continue

    return [
        "1. Présence & Disponibilité en Rayon : Alerter les équipes commerciales sur les points de vente présentant des ruptures critiques afin de rétablir les facings avant le pic d'affluence du week-end.",
        "2. Négociation Enseignes : Organiser une revue de compte avec les enseignes sous le seuil de 80% de conformité facing pour demander le respect strict du planogramme contractuel.",
        "3. Arbitrage Budgétaire : Réallouer 25% du budget d'audit des zones conformes (>90%) vers les provinces à fort potentiel commercial afin de maximiser le retour sur investissement."
    ]


# ==================== ENDPOINTS DE L'API ====================

@app.get("/")
@app.get("/api")
async def root():
    return {
        "status": "online",
        "service": "Microservice IA Superviseur (Retail Intelligence)",
        "version": "2.0.0",
        "features": [
            "Génération intelligente de fiches d'audit depuis brief/prompt mission (Gemini)",
            "Synthèse exécutive & Recommandations stratégiques multi-réseaux"
        ],
        "diagnostics": {
            "gemini_ready": gemini_client is not None,
            "gemini_error": gemini_error,
            "firebase_ready": db is not None,
            "firebase_error": firebase_error,
        },
        "endpoints": {
            "generate_questions": "POST /api/generate-questions",
            "strategic_advice": "POST /api/strategic-advice",
            "health": "GET /api/health",
            "docs": "/docs"
        }
    }

@app.get("/health")
@app.get("/api/health")
async def health():
    return {"ok": True, "gemini": gemini_client is not None}

@app.post("/generate-questions")
@app.post("/api/generate-questions")
async def endpoint_generate_questions(payload: dict):
    """Génération dynamique et intelligente d'un questionnaire d'audit par IA."""
    try:
        result = await generer_questions_gemini(payload or {})
        return result
    except Exception as e:
        print(f"❌ Erreur génération questions : {e}")
        return generer_questions_fallback(payload or {})

@app.api_route("/strategic-advice", methods=["GET", "POST", "OPTIONS"])
@app.api_route("/api/strategic-advice", methods=["GET", "POST", "OPTIONS"])
async def endpoint_strategic_advice(request: Request):
    """Génération de recommandations stratégiques consolidées par IA."""
    if request.method == "OPTIONS":
        return JSONResponse(status_code=200, content={"status": "ok"})

    payload = {}
    if request.method == "POST":
        try:
            payload = await request.json()
        except Exception:
            payload = {}

    try:
        conseils = await obtenir_conseil_strategique_gemini(payload or {})
        return {
            "status": "ok",
            "conseils": conseils,
            "count": len(conseils)
        }
    except Exception as e:
        print(f"❌ Erreur recommandation stratégique : {e}")
        return {
            "status": "fallback",
            "conseils": [
                "1. Logistique : Renforcer les livraisons du vendredi matin sur les hypermarchés cibles.",
                "2. Négociation : Demander un plan de redressement de facing auprès des enseignes sous les 80%.",
                "3. Budget : Rééquilibrer les budgets d'audit vers les zones en croissance."
            ]
        }

@app.api_route("/{full_path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"])
async def catch_all_dispatcher(request: Request, full_path: str):
    if request.method == "OPTIONS":
        return JSONResponse(status_code=200, content={"status": "ok"})

    clean_path = full_path.lower().strip("/")

    if "generate" in clean_path or "question" in clean_path:
        body = {}
        try:
            body = await request.json()
        except Exception:
            pass
        return await endpoint_generate_questions(body)

    if "strategic" in clean_path:
        return await endpoint_strategic_advice(request)

    if "health" in clean_path:
        return {"ok": True, "gemini": gemini_client is not None}

    return await root()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)