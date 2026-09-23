# Local Flatpak builds for testing. CI (.github/workflows/flatpak.yml) does the
# signed release builds; this is for trying changes on your own machine.
#
#   make deps      one-time: install the KDE runtime + SDK from Flathub
#   make install   build and install (replacing any installed Hey Whisper)
#   make run       launch the installed app
#
# Run `make help` for everything else.

APP_ID   := org.heywhisper.HeyWhisper
MANIFEST := $(APP_ID).yaml

BUILD_DIR := build-dir
# Kept apart from repo/, which CI and the gh-pages publish use
LOCAL_REPO := .flatpak-repo
BUNDLE     := hey-whisper-local.flatpak

# Remote to reinstall the released build from (`make restore`), as named by
# `flatpak remote-add ... hey-whisper` in the README
RELEASE_REMOTE ?= hey-whisper

# Extra flags, e.g. FB_FLAGS=--disable-rofiles-fuse or FB_FLAGS=--ccache
FB_FLAGS ?=

RUNTIME         := $(shell sed -n 's/^runtime: *//p' $(MANIFEST))
SDK             := $(shell sed -n 's/^sdk: *//p' $(MANIFEST))
RUNTIME_VERSION := $(shell sed -n "s/^runtime-version: *'\{0,1\}\([^']*\)'\{0,1\}/\1/p" $(MANIFEST))

.DEFAULT_GOAL := help

.PHONY: help deps build install run run-cli shell bundle uninstall restore clean distclean

help: ## Show this help
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "} {printf "  make %-10s %s\n", $$1, $$2}'

deps: ## Install the Flatpak runtime and SDK the manifest needs (one-time)
	flatpak remote-add --user --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
	flatpak install --user -y --noninteractive flathub $(RUNTIME)//$(RUNTIME_VERSION) $(SDK)//$(RUNTIME_VERSION)

build: ## Build the app into a local Flatpak repo
	flatpak-builder --user --force-clean $(FB_FLAGS) --repo=$(LOCAL_REPO) $(BUILD_DIR) $(MANIFEST)

install: build ## Build, then install it for your user (replaces an installed release)
	flatpak install --user -y --noninteractive --reinstall $(LOCAL_REPO) $(APP_ID)

run: ## Run the installed app
	flatpak run $(APP_ID)

run-cli: ## Run the installed app in CLI mode
	flatpak run $(APP_ID) --cli

shell: ## Open a shell inside the installed app's sandbox
	flatpak run --command=sh $(APP_ID)

bundle: build ## Build hey-whisper-local.flatpak to copy to another machine
	flatpak build-bundle --runtime-repo=https://dl.flathub.org/repo/flathub.flatpakrepo $(LOCAL_REPO) $(BUNDLE) $(APP_ID)
	@ls -lh $(BUNDLE)

uninstall: ## Uninstall the app for your user
	flatpak uninstall --user -y --noninteractive $(APP_ID)

restore: ## Reinstall the published release (RELEASE_REMOTE=hey-whisper)
	flatpak install --user -y --noninteractive --reinstall $(RELEASE_REMOTE) $(APP_ID)

clean: ## Remove the build directory, local repo and bundle
	rm -rf $(BUILD_DIR) $(LOCAL_REPO) $(BUNDLE)

distclean: clean ## Also remove flatpak-builder's download/module cache (next build is slow)
	rm -rf .flatpak-builder
