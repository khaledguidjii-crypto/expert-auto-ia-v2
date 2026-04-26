import streamlit as st
import base64
import json
import re
import os
from io import BytesIO
import tempfile
from docxtpl import DocxTemplate, InlineImage
from docx.shared import Mm
from openai import OpenAI

st.set_page_config(page_title="Expert Auto IA", page_icon="🚗", layout="wide")

# ====================== CONFIGURATION OPENAI ======================
if "client" not in st.session_state:
    try:
        api_key = st.secrets["OPENAI_API_KEY"]
    except:
        try:
            import config
            api_key = config.OPENAI_API_KEY
        except:
            api_key = os.getenv("OPENAI_API_KEY")
    
    if not api_key:
        st.error("❌ Clé OpenAI non trouvée ! Ajoute-la dans Streamlit Secrets.")
        st.stop()
    
    st.session_state.client = OpenAI(api_key=api_key)

client = st.session_state.client

# ====================== FONCTIONS ======================
def log_msg(msg):
    if "logs" not in st.session_state:
        st.session_state.logs = []
    st.session_state.logs.append(msg)

def extract_vin_protocol(vin_bytes=None, plaque_bytes=None):
    sources = [("VIN gravé", vin_bytes), ("Plaque", plaque_bytes)]
    for name, img_bytes in sources:
        if not img_bytes: continue
        try:
            img_b64 = base64.b64encode(img_bytes).decode()
            res = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": [
                    {"type": "text", "text": "Retourne UNIQUEMENT le VIN complet de 17 caractères. Rien d'autre."},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}}
                ]}]
            )
            clean = re.sub(r'[^A-Z0-9]', '', res.choices[0].message.content.strip().upper())
            if len(clean) == 17:
                log_msg(f"✅ VIN trouvé : {clean}")
                return clean
        except: pass
    log_msg("❌ Aucun VIN valide trouvé")
    return ""

def extract_plaque_poids(plaque_bytes):
    if not plaque_bytes: return {"ptac": "Non disponible", "ptra": "Non disponible"}
    try:
        img_b64 = base64.b64encode(plaque_bytes).decode()
        prompt = "Analyse cette plaque métallique. Retourne UNIQUEMENT JSON : {\"ptac\": \"XXXX\", \"ptra\": \"XXXX\"}"
        res = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}}
            ]}]
        )
        text = res.choices[0].message.content.replace("```json","").replace("```","").strip()
        data = json.loads(text)
        return {
            "ptac": re.sub(r'[^0-9]', '', str(data.get("ptac", ""))) or "Non disponible",
            "ptra": re.sub(r'[^0-9]', '', str(data.get("ptra", ""))) or "Non disponible"
        }
    except:
        return {"ptac": "Non disponible", "ptra": "Non disponible"}

def extract_carte_grise_protocol(carte_bytes):
    try:
        img_b64 = base64.b64encode(carte_bytes).decode()
        prompt = """Lis cette carte grise algérienne. Retourne UNIQUEMENT ce JSON :
        {"marque": "", "Genre": "", "type": "", "carrosserie": "", "immatriculation": "", "date_premiere_circulation": "", "puissance_administrative": "", "nombre_places_assises": ""}"""
        res = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}}
            ]}]
        )
        text = res.choices[0].message.content.replace("```json","").replace("```","").strip()
        return json.loads(text)
    except:
        return {}

def generate_report(cg_data, vin_complet, poids_plaque, infos, images_bytes):
    if not os.path.exists("modele.docx"):
        st.error("❌ modele.docx introuvable !")
        return None

    with tempfile.TemporaryDirectory() as tmpdir:
        doc = DocxTemplate("modele.docx")

        if vin_complet and len(vin_complet) == 17:
            cg_data["vin_complet"] = vin_complet
            cg_data["vin_9"] = vin_complet[:9]
            cg_data["vin_8"] = vin_complet[9:]
        else:
            cg_data["vin_complet"] = cg_data["vin_9"] = cg_data["vin_8"] = "Non disponible"

        cg_data["ptac"] = poids_plaque.get("ptac", "1500") if str(poids_plaque.get("ptac","")) != "Non disponible" else "1500"
        cg_data["ptra"] = poids_plaque.get("ptra", "2300") if str(poids_plaque.get("ptra","")) != "Non disponible" else "2300"

        defaults = {"nb_cylindres": "4", "cylindree": "1400", "boite_vitesse": "Manuelle", "poids_vide": "1100", "charge_utile": "400"}
        for k, v in defaults.items():
            if k not in cg_data or not cg_data.get(k):
                cg_data[k] = v

        final = {**cg_data, **infos}

        for key, img_bytes in images_bytes.items():
            if img_bytes:
                path = os.path.join(tmpdir, f"{key}.jpg")
                with open(path, "wb") as f:
                    f.write(img_bytes)
                final[f"img_{key}"] = InlineImage(doc, path, height=Mm(45))

        doc.render(final)
        buffer = BytesIO()
        doc.save(buffer)
        buffer.seek(0)
        return buffer

# ====================== INTERFACE ======================
st.title("🚗 Expert Auto IA")
st.markdown("**Rapport d’expertise véhicule**")
st.info("📱 **iPhone** : Utilise **Chrome** pour une meilleure compatibilité caméra")

st.header("📸 Documents & Photos")
cols = st.columns(4)
keys = ["carte", "vin", "plaque", "vehicule"]
labels = ["📄 Carte Grise", "🔢 VIN gravé", "🔖 Plaque", "🚙 Photo Véhicule"]

images_bytes = {}

for i, (key, label) in enumerate(zip(keys, labels)):
    with cols[i]:
        st.subheader(label)
        
        col_u, col_c = st.columns(2)
        with col_u:
            uploaded = st.file_uploader("📤 Uploader", type=["jpg","jpeg","png"], key=f"upload_{key}")
        with col_c:
            camera = st.camera_input("📸 Caméra", key=f"camera_{key}")
        
        current_bytes = None
        if camera is not None:
            current_bytes = camera.getvalue()
            st.success("✅ Photo prise avec caméra")
        elif uploaded is not None:
            current_bytes = uploaded.getvalue()
            st.success("✅ Photo uploadée")
        
        if current_bytes:
            st.image(current_bytes, width=200)
            images_bytes[key] = current_bytes

st.header("📝 Informations Complémentaires")
col1, col2 = st.columns(2)
with col1:
    nom = st.text_input("Nom propriétaire", "")
    num_rapport = st.text_input("Numéro rapport", "001")
    lieu = st.text_input("Lieu", "TISSEMSILT")
with col2:
    date_exp = st.text_input("Date expertise", "26/04/2026")
    couleur = st.text_input("Couleur", "")
    carburant = st.text_input("Carburant", "Essence")

infos = {
    "nom_proprietaire": nom,
    "num_rapport": num_rapport,
    "lieu": lieu,
    "date_expertise": date_exp,
    "couleur": couleur,
    "carburant": carburant
}

if st.button("🚀 ANALYSER AVEC IA ET GÉNÉRER RAPPORT", type="primary", use_container_width=True):
    if not images_bytes.get("carte"):
        st.error("❌ La Carte Grise est obligatoire !")
    else:
        with st.spinner("Analyse en cours avec GPT-4o-mini..."):
            cg_data = extract_carte_grise_protocol(images_bytes["carte"])
            vin_complet = extract_vin_protocol(images_bytes.get("vin"), images_bytes.get("plaque"))
            poids_plaque = extract_plaque_poids(images_bytes.get("plaque"))
            
            buffer = generate_report(cg_data, vin_complet, poids_plaque, infos, images_bytes)

        if buffer:
            st.success("✅ Rapport généré avec succès !")
            st.download_button(
                label="📥 Télécharger le rapport Word",
                data=buffer,
                file_name=f"rapport_{num_rapport}.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                use_container_width=True
            )

st.caption("💡 Sur iPhone : essaie avec Google Chrome si la caméra ne fonctionne pas")