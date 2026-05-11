-include .env
-include $(HOME)/.config/cube/config
ifndef CUBE_IP
$(error CUBE_IP not set — copy .env.example to .env or write CUBE_IP=<ip> to ~/.config/cube/config)
endif
export CUBE_IP

BIN := ./bin
ASSETS_128 := assets
ASSETS_240 := assets/240

.PHONY: help ping info resize upload deploy cycle clear-old all status

help:
	@echo "cube — Geekmagic SmallTV-Ultra status display"
	@echo
	@echo "Targets:"
	@echo "  make ping        - check device reachable at $(CUBE_IP)"
	@echo "  make info        - dump device version + state + free space"
	@echo "  make resize      - 128x128 -> 240x240 (gifsicle nearest-neighbor)"
	@echo "  make upload      - push resized GIFs to /image/ on cube"
	@echo "  make all         - resize + upload"
	@echo "  make deploy      - install cube.sh + cube-gen.py to ~/.claude/bin/"
	@echo "  make cycle       - visual smoke-test: thinking -> alert -> idle"
	@echo "  make clear-old   - dry-run delete-everything-except-status-gifs on cube"
	@echo "                     (add FORCE=1 to actually delete)"
	@echo "  make status      - show local assets + cube file listing"

ping:
	@$(BIN)/cube.sh ping

info:
	@$(BIN)/cube.sh info

resize:
	@$(BIN)/resize.sh

upload:
	@$(BIN)/upload.sh

all: resize upload

deploy:
	@$(BIN)/deploy.sh

cycle:
	@$(BIN)/cycle.sh

clear-old:
ifeq ($(FORCE),1)
	@$(BIN)/clear-old.sh --force
else
	@$(BIN)/clear-old.sh
endif

status:
	@echo "=== local assets/ ==="
	@ls -la $(ASSETS_128)/*.gif 2>/dev/null || echo "  (none)"
	@echo
	@echo "=== local assets/240/ ==="
	@ls -la $(ASSETS_240)/*.gif 2>/dev/null || echo "  (none)"
	@echo
	@echo "=== cube /image/ ==="
	@curl -fsS -m 5 "http://$(CUBE_IP)/filelist?dir=/image/" \
		| grep -oP "href='/image/[^']+'" | sed "s|href='/image//*|  |; s|'$$||" \
		|| echo "  (unreachable)"
	@echo
	@echo "=== cube space ==="
	@curl -fsS -m 3 "http://$(CUBE_IP)/space.json" || echo "(unreachable)"
	@echo
