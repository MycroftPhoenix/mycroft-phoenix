#!/usr/bin/env python3
"""Gestionnaire de chemins de données pour Phoenix."""
import os
import sys
import json
import platform
from pathlib import Path


class DataManager:
    """Gère les chemins de données pour Phoenix."""
    
    def __init__(self, config_path=None):
        self.system = platform.system()
        self.config_path = config_path
        self._config = None
        self._data_dir = None
        
    def get_default_data_dir(self):
        """Retourne le répertoire de données par défaut."""
        if self.system == "Windows":
            return Path(os.environ.get('LOCALAPPDATA', '')) / 'Phoenix'
        elif self.system == "Darwin":  # macOS
            return Path.home() / 'Library' / 'Application Support' / 'Phoenix'
        else:  # Linux
            return Path.home() / '.local' / 'share' / 'Phoenix'
    
    def get_data_dir(self):
        """Retourne le répertoire de données configuré."""
        if self._data_dir:
            return self._data_dir
            
        config = self._load_config()
        if config and 'data_directory' in config:
            self._data_dir = Path(config['data_directory'])
        else:
            self._data_dir = self.get_default_data_dir()
            
        # Créer le répertoire s'il n'existe pas
        self._data_dir.mkdir(parents=True, exist_ok=True)
        return self._data_dir
    
    def set_data_dir(self, path):
        """Définit le répertoire de données."""
        self._data_dir = Path(path)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        
        # Mettre à jour la config
        config = self._load_config() or {}
        config['data_directory'] = str(self._data_dir)
        self._save_config(config)
        
        return self._data_dir
    
    def get_kuzu_path(self):
        """Retourne le chemin vers la base Kuzu."""
        return self.get_data_dir() / 'kuzu'
    
    def get_config_path(self):
        """Retourne le chemin vers phoenix_config.json."""
        if self.config_path:
            return Path(self.config_path)
        return self.get_data_dir() / 'phoenix_config.json'
    
    def get_models_path(self):
        """Retourne le chemin vers les modèles."""
        return self.get_data_dir() / 'models'
    
    def get_vosk_path(self):
        """Retourne le chemin vers le modèle Vosk."""
        return self.get_models_path() / 'vosk-model-fr-0.22'
    
    def get_piper_path(self):
        """Retourne le chemin vers les voix Piper."""
        return self.get_models_path() / 'piper' / 'voices'
    
    def get_logs_path(self):
        """Retourne le chemin vers les logs."""
        logs_dir = self.get_data_dir() / 'logs'
        logs_dir.mkdir(exist_ok=True)
        return logs_dir
    
    def _load_config(self):
        """Charge la configuration."""
        if self._config:
            return self._config
            
        # Utiliser le chemin fourni ou le répertoire par défaut
        if self.config_path:
            config_path = Path(self.config_path)
        else:
            # Utiliser le répertoire par défaut sans boucle
            config_path = self.get_default_data_dir() / 'phoenix_config.json'
        
        if config_path.exists():
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    self._config = json.load(f)
            except Exception:
                self._config = {}
        else:
            self._config = {}
            
        return self._config
    
    def _save_config(self, config=None):
        """Sauvegarde la configuration."""
        if config:
            self._config = config
            
        config_path = self.get_config_path()
        try:
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(self._config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Erreur sauvegarde config: {e}")
    
    def is_first_run(self):
        """Vérifie si c'est le premier lancement."""
        return not self.get_config_path().exists()
    
    def get_status(self):
        """Retourne le statut des données."""
        data_dir = self.get_data_dir()
        kuzu_dir = self.get_kuzu_path()
        
        return {
            'data_dir': str(data_dir),
            'data_dir_exists': data_dir.exists(),
            'kuzu_dir': str(kuzu_dir),
            'kuzu_exists': kuzu_dir.exists(),
            'first_run': self.is_first_run()
        }


# Instance globale
_manager = None


def get_manager():
    """Retourne l'instance globale du DataManager."""
    global _manager
    if _manager is None:
        _manager = DataManager()
    return _manager


if __name__ == "__main__":
    # Test
    dm = DataManager()
    print("=== DataManager Test ===")
    print(f"Système: {platform.system()}")
    print(f"Répertoire par défaut: {dm.get_default_data_dir()}")
    print(f"Répertoire actuel: {dm.get_data_dir()}")
    print(f"Statut: {dm.get_status()}")
