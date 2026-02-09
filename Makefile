UV ?= uv
PIP_CACHE ?= $(HOME)/.cache/pip
ARM_IMAGE ?= just-talk-linux-arm
ARM_PLATFORM ?= linux/arm64
PYINSTALLER_IMAGE ?= fydeinc/pyinstaller
WIN_BINARY_NAME ?= just-talk-win64
WIN_PIP_ARGS ?= -i https://pypi.tuna.tsinghua.edu.cn/simple
WIN_SHELL_CMDS ?= /usr/win64/bin/pip install $(WIN_PIP_ARGS) -U pyinstaller==6.18.0 pyinstaller-hooks-contrib
WIN_ONEFILE ?= 1
WIN_CONSOLE ?= 0
WIN_ICON_PNG ?= icon.png
WIN_ICON ?= icon.ico
ICON_CONVERT ?= $(shell command -v convert 2>/dev/null || command -v magick 2>/dev/null)
FIX_PERMS ?= 1
CHOWN ?= sudo chown
CHOWN_USER ?= $(shell id -u):$(shell id -g)
APPIMAGETOOL ?= appimagetool-x86_64.AppImage
APPIMAGETOOL_URL ?= https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage
VERSION ?= $(shell python -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])")
APPIMAGE_IMAGE ?= just-talk-linux-appimage

.PHONY: sync build-linux build-appimage build-appimage-local docker-appimage-image build-windows build-macos build-dmg build-all clean-dist

sync:
	$(UV) sync --frozen --extra build

build-linux: sync
	JT_BINARY_NAME=just-talk-x86_64 JT_ONEFILE=1 $(UV) run pyinstaller just_talk.spec

build-appimage-local: build-linux
	@# Download appimagetool if not exists
	@if [ ! -f "$(APPIMAGETOOL)" ]; then \
		echo "Downloading appimagetool..."; \
		wget -q "$(APPIMAGETOOL_URL)" -O "$(APPIMAGETOOL)"; \
		chmod +x "$(APPIMAGETOOL)"; \
	fi
	@# Create AppDir structure
	rm -rf AppDir
	mkdir -p AppDir/usr/bin
	mkdir -p AppDir/usr/share/applications
	mkdir -p AppDir/usr/share/icons/hicolor/256x256/apps
	@# Copy binary
	cp dist/just-talk-x86_64 AppDir/usr/bin/just-talk
	@# Copy icon
	@if [ -f icon.png ]; then \
		cp icon.png AppDir/usr/share/icons/hicolor/256x256/apps/just-talk.png; \
		cp icon.png AppDir/just-talk.png; \
	fi
	@# Create desktop file
	@echo '[Desktop Entry]' > AppDir/just-talk.desktop
	@echo 'Type=Application' >> AppDir/just-talk.desktop
	@echo 'Name=Just Talk' >> AppDir/just-talk.desktop
	@echo 'Exec=just-talk' >> AppDir/just-talk.desktop
	@echo 'Icon=just-talk' >> AppDir/just-talk.desktop
	@echo 'Terminal=false' >> AppDir/just-talk.desktop
	@echo 'Categories=AudioVideo;Audio;' >> AppDir/just-talk.desktop
	@echo 'Comment=Speech recognition with global hotkey support' >> AppDir/just-talk.desktop
	cp AppDir/just-talk.desktop AppDir/usr/share/applications/
	@# Create AppRun
	@echo '#!/bin/bash' > AppDir/AppRun
	@echo 'SELF=$$(readlink -f "$$0")' >> AppDir/AppRun
	@echo 'HERE=$${SELF%/*}' >> AppDir/AppRun
	@echo 'export PATH="$${HERE}/usr/bin:$${PATH}"' >> AppDir/AppRun
	@echo 'exec "$${HERE}/usr/bin/just-talk" "$$@"' >> AppDir/AppRun
	chmod +x AppDir/AppRun
	@# Build AppImage
	ARCH=x86_64 ./$(APPIMAGETOOL) AppDir "dist/just-talk-$(VERSION)-x86_64.AppImage"
	@echo "AppImage created: dist/just-talk-$(VERSION)-x86_64.AppImage"

docker-appimage-image:
	docker build -f Dockerfile.linux-appimage -t $(APPIMAGE_IMAGE) .

build-appimage: docker-appimage-image
	docker run --rm \
		-v $(PWD):/app \
		-w /app \
		$(APPIMAGE_IMAGE) \
		bash scripts/build-appimage.sh
	@if [ "$(FIX_PERMS)" = "1" ]; then \
		if [ -d dist ] || [ -d build ]; then \
			$(CHOWN) -R $(CHOWN_USER) dist build AppDir; \
		fi; \
	fi

release-linux:
	./scripts/release-linux.sh

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

build-macos: sync
	@if [ -f icon.png ] && [ ! -f icon.icns ]; then \
		echo "Generating icon.icns..."; \
		mkdir -p icon.iconset; \
		for size in 16 32 64 128 256 512 1024; do \
			sips -z $$size $$size icon.png --out icon.iconset/icon_$${size}.png > /dev/null; \
		done; \
		cp icon.iconset/icon_16.png icon.iconset/icon_16x16.png; \
		cp icon.iconset/icon_32.png icon.iconset/icon_16x16@2x.png; \
		cp icon.iconset/icon_32.png icon.iconset/icon_32x32.png; \
		cp icon.iconset/icon_64.png icon.iconset/icon_32x32@2x.png; \
		cp icon.iconset/icon_128.png icon.iconset/icon_128x128.png; \
		cp icon.iconset/icon_256.png icon.iconset/icon_128x128@2x.png; \
		cp icon.iconset/icon_256.png icon.iconset/icon_256x256.png; \
		cp icon.iconset/icon_512.png icon.iconset/icon_256x256@2x.png; \
		cp icon.iconset/icon_512.png icon.iconset/icon_512x512.png; \
		cp icon.iconset/icon_1024.png icon.iconset/icon_512x512@2x.png; \
		iconutil -c icns icon.iconset -o icon.icns; \
		rm -rf icon.iconset; \
	fi
	JT_ONEFILE=0 JT_ICON=icon.icns $(UV) run pyinstaller just_talk.spec

build-dmg: build-macos
	@rm -rf dist/dmg-staging
	@mkdir -p dist/dmg-staging
	cp -R "dist/Just Talk.app" dist/dmg-staging/
	ln -s /Applications dist/dmg-staging/Applications
	hdiutil create -volname "Just Talk" \
		-srcfolder dist/dmg-staging \
		-ov -format UDZO \
		"dist/just-talk-macos-$(VERSION).dmg"
	@rm -rf dist/dmg-staging
	@echo "DMG created: dist/just-talk-macos-$(VERSION).dmg"

build-all: build-linux build-windows

clean-dist:
	rm -rf build dist
