-include .env
-include $(HOME)/.config/cube/config

BIN := ./bin

.PHONY: help deploy dev-install mock

help:
	@echo "cube — Claude-Code multi-session overlay (voxel entity)"
	@echo
	@echo "Targets:"
	@echo "  make deploy      - install cube.sh + mock-cube.py + mock-cube.service to ~/.claude/"
	@echo "  make dev-install - deploy + enable systemd --user mock-cube unit"
	@echo "  make mock        - run mock-cube.py in foreground (Ctrl-C to stop)"

deploy:
	@$(BIN)/deploy.sh

dev-install:
	@$(BIN)/deploy.sh
	@systemctl --user daemon-reload
	@systemctl --user enable --now mock-cube
	@systemctl --user status mock-cube --no-pager -n 3

mock:
	@$(BIN)/mock-cube.py
