"""Sources de données historiques pour le backtest (Phase 1).

L'export MT5 est la source privilégiée : c'est le code déjà éprouvé de
l'ancien bot (data_extractor.py / mt5_connection.py à la racine) et ça
garantit une structure identique entre « données de backtest » et
« données que le futur MT5Connector verra en live ».
"""