# Agent — Base de données de mémoire (LadybugDB)

## Emplacement
C:\Users\Administrateur\.config\opencode\memory-server\memory.lbdb

## Description
Base de données graphe LadybugDB utilisée pour la mémoire du projet
mycroft-phoenix. Elle documente toutes les modifications apportées au
projet et leurs raisons, sous forme de Domaines (azelia, exchanges,
learnings, projects, ...) et d'Entry reliées par BELONGS_TO.

## Accès
- MCP : serveur "ladybugdb" (mcp-server-ladybug) configuré dans
  C:\Users\Administrateur\.config\opencode\opencode.jsonc
- Le domaine "projects" contient les modifications du projet Phoenix.

## Dernière modification documentée
Entry `projects-016` (2026-08-15) : session stabilité + spec Steve
(file FIFO concurrence, skill date_time réparé, heure/date réelles,
architecture fallback_only, skill histoire activable + choix de l'IA).

## Fichiers liés
- Config MCP : C:\Users\Administrateur\.config\opencode\opencode.jsonc
- Graphe module_map : C:\Users\Administrateur\.config\opencode\graphs\module_map.lbdb
