"""
Géolocalisation pour les ressources de crise.

Approche hybride:
1. Config manuelle (prioritaire, zéro dépendance)
2. GeoLite2 (fallback automatique, offline)
3. Fallback international (befrienders.org)
"""

import json
import logging
from pathlib import Path
from typing import Optional, Dict

logger = logging.getLogger(__name__)

RESOURCES_PATH = Path(__file__).parent.parent.parent / "data" / "emergency_resources.json"
CONFIG_PATH = Path.home() / ".config" / "phoenix" / "user_location.json"
GEOLITE_DB_PATH = Path.home() / ".config" / "phoenix" / "GeoLite2-Country.mmdb"


class CrisisLocator:
    """
    Détermine la localisation de l'utilisateur et retourne
    les ressources de crise appropriées.
    """

    def __init__(self):
        self._resources: Optional[Dict] = None
        self._config: Optional[Dict] = None
        self._geo_reader = None

    def initialize(self):
        """Charge les ressources et la config."""
        self._load_resources()
        self._load_config()
        self._init_geolite()

    def _load_resources(self):
        """Charge emergency_resources.json."""
        if RESOURCES_PATH.exists():
            with open(RESOURCES_PATH, "r", encoding="utf-8") as f:
                self._resources = json.load(f)
            logger.info(f"Ressources chargées: {len(self._resources.get('localizations', {}))} pays")
        else:
            logger.warning(f"Fichier ressources non trouvé: {RESOURCES_PATH}")
            self._resources = {}

    def _load_config(self):
        """Charge la config manuelle de l'utilisateur."""
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                self._config = json.load(f)
            logger.info(f"Config utilisateur chargée: pays={self._config.get('country_code', 'auto')}")
        else:
            self._config = {}

    def _init_geolite(self):
        """Initialise la lecture GeoLite2 si disponible."""
        try:
            import geoip2.database
            import geoip2.errors
            if GEOLITE_DB_PATH.exists():
                self._geo_reader = geoip2.database.Reader(str(GEOLITE_DB_PATH))
                logger.info("GeoLite2 chargé")
            else:
                logger.info("GeoLite2 non trouvé, mode config uniquement")
        except ImportError:
            logger.info("geoip2 non installé, mode config uniquement")

    def get_user_country(self, ip_address: Optional[str] = None) -> Optional[str]:
        """
        Détermine le code pays de l'utilisateur.

        Priorité:
        1. Config manuelle (user_location.json)
        2. GeoLite2 (si IP fournie)
        3. None (fallback international)
        """
        # 1. Config manuelle
        if self._config and "country_code" in self._config:
            return self._config["country_code"].upper()

        # 2. GeoLite2
        if self._geo_reader and ip_address:
            try:
                response = self._geo_reader.country(ip_address)
                return response.country.iso_code
            except Exception as e:
                logger.warning(f"Erreur GeoLite2 pour {ip_address}: {e}")

        return None

    def get_resources(self, country_code: Optional[str] = None, region_code: Optional[str] = None) -> Dict:
        """
        Retourne les ressources de crise pour un pays/région.

        Args:
            country_code: Code ISO 3166-1 (ex: CA, FR, US)
            region_code: Code régional (ex: QC pour Québec)
        """
        if not self._resources:
            return self._get_fallback_response()

        localizations = self._resources.get("localizations", {})

        # Chercher le pays
        if country_code and country_code.upper() in localizations:
            country_data = localizations[country_code.upper()]

            # Vérifier si une région spécifique existe
            if region_code and "regional" in country_data:
                region_key = region_code.upper()
                if region_key in country_data["regional"]:
                    region_data = country_data["regional"][region_key]
                    return {
                        "country": country_data.get("country", country_code),
                        "region": region_key,
                        "crisis_line": region_data.get("name", ""),
                        "phone": region_data.get("phone", ""),
                        "text": region_data.get("text", ""),
                        "web": region_data.get("web", ""),
                        "spoken_response": country_data.get("spoken_response", self._resources.get("default_response", "")),
                    }

            # Retourner les données nationales
            crisis = country_data.get("crisis_line", {})
            return {
                "country": country_data.get("country", country_code),
                "crisis_line": crisis.get("name", ""),
                "phone": crisis.get("phone", ""),
                "text": crisis.get("text", ""),
                "web": crisis.get("web", ""),
                "spoken_response": country_data.get("spoken_response", self._resources.get("default_response", "")),
            }

        # Fallback: directories internationales
        return self._get_fallback_response()

    def _get_fallback_response(self) -> Dict:
        """Réponse de fallback avec répertoires internationaux."""
        dirs = self._resources.get("international_directories", {})
        return {
            "country": "International",
            "crisis_line": "Find a Helpline",
            "phone": "",
            "text": "",
            "web": dirs.get("findahelpline", "https://findahelpline.com"),
            "spoken_response": "Je vous entends. Vous pouvez trouver une ligne d'aide dans votre pays sur findahelpline.com",
        }

    def set_country(self, country_code: str, region_code: Optional[str] = None):
        """
        Définit manuellement le pays de l'utilisateur.
        Sauvegarde dans user_location.json.
        """
        self._config = {
            "country_code": country_code.upper(),
            "region_code": region_code.upper() if region_code else None,
        }

        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(self._config, f, indent=2, ensure_ascii=False)

        logger.info(f"Pays défini: {country_code}" + (f"/{region_code}" if region_code else ""))

    def list_available_countries(self) -> list:
        """Retourne la liste des pays disponibles."""
        if not self._resources:
            return []
        return list(self._resources.get("localizations", {}).keys())

    def shutdown(self):
        """Ferme les ressources."""
        if self._geo_reader:
            self._geo_reader.close()
