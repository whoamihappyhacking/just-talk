UV ?= uv
PIP_CACHE ?= $(HOME)/.cache/pip
ARM_IMAGE ?= just-talk-linux-arm
ARM_PLATFORM ?= linux/arm64
PYINSTALLER_IMAGE ?= fydeinc/pyinstaller
PYINSTALLER_PYPI_URL ?= https://pypi.tuna.tsinghua.edu.cn/
PYINSTALLER_PYPI_INDEX_URL ?= https://pypi.tuna.tsinghua.edu.cn/simple
WIN_BINARY_NAME ?= just-talk-win64
WIN_PIP_ARGS ?= -i $(PYINSTALLER_PYPI_INDEX_URL) --trusted-host pypi.tuna.tsinghua.edu.cn
WIN_SHELL_CMDS ?= /usr/win64/bin/pip install $(WIN_PIP_ARGS) -U pyinstaller==6.18.0 pyinstaller-hooks-contrib
WIN_ONEFILE ?= 1
WIN_CONSOLE ?= 0
WIN_ICON_PNG ?= icon.png
WIN_ICON ?= icon.ico
ICON_CONVERT ?= $(shell command -v convert 2>/dev/null || command -v magick 2>/dev/null)
FIX_PERMS ?= 1
CHOWN ?= sudo chown
CHOWN_USER ?= $(shell id -u):$(shell id -g)

.PHONY: sync build-linux build-windows build-all clean-dist

sync:
	$(UV) sync --frozen --extra build

build-linux: sync
	JT_BINARY_NAME=just-talk-x86_64 $(UV) run pyinstaller just_talk.spec

build-windows:
	@if [ -f "$(WIN_ICON_PNG)" ] && [ ! -f "$(WIN_ICON)" ]; then \
		if [ -n "$(ICON_CONVERT)" ]; then \
			"$(ICON_CONVERT)" "$(WIN_ICON_PNG)" -define icon:auto-resize=256,128,64,48,32,16 "$(WIN_ICON)"; \
		else \
			echo "icon.png found but no image conversion tool available; install ImageMagick or provide icon.ico"; \
			exit 1; \
		fi; \
	fi
	docker run --rm \
		--entrypoint bash \
		-v $(PWD):/src \
		-v $(PIP_CACHE):/root/.cache/pip \
		-e PIP_INDEX_URL=$(PYINSTALLER_PYPI_INDEX_URL) \
		-e PIP_TRUSTED_HOST=pypi.tuna.tsinghua.edu.cn \
		-e JT_BINARY_NAME=$(WIN_BINARY_NAME) \
		-e JT_ICON=$(WIN_ICON) \
		-e JT_ONEFILE=$(WIN_ONEFILE) \
		-e JT_CONSOLE=$(WIN_CONSOLE) \
		$(PYINSTALLER_IMAGE) \
		-lc 'set -eux; cd /src; if [ -f requirements.txt ]; then /usr/win64/bin/pip install $(WIN_PIP_ARGS) -r requirements.txt; fi; $(WIN_SHELL_CMDS); /usr/win64/bin/pyinstaller just_talk.spec'
	@if [ "$(FIX_PERMS)" = "1" ]; then \
		if [ -d dist ] || [ -d build ]; then \
			$(CHOWN) -R $(CHOWN_USER) dist build; \
		fi; \
	fi

docker-linux-arm-image:
	docker build --platform $(ARM_PLATFORM) -f Dockerfile.linux-arm -t $(ARM_IMAGE) .

build-linux-arm: docker-linux-arm-image
	docker run --rm --platform $(ARM_PLATFORM) \
		-v $(PWD):/app \
		-v $(PIP_CACHE):/root/.cache/pip \
		-w /app \
		$(ARM_IMAGE) \
		bash -lc "JT_BINARY_NAME=just-talk-arm64 pyinstaller just_talk.spec"
	@if [ "$(FIX_PERMS)" = "1" ]; then \
		if [ -d dist ] || [ -d build ]; then \
			$(CHOWN) -R $(CHOWN_USER) dist build; \
		fi; \
	fi

build-all: build-linux build-windows

clean-dist:
	rm -rf build dist
