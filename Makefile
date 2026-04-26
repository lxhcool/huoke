.PHONY: dev dev-win

dev:
	bash scripts/dev.sh

dev-win:
	powershell -ExecutionPolicy Bypass -File scripts/dev.ps1
