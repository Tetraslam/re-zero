SKETCH ?= esp32_sta
PORT ?= /dev/ttyUSB1
AP_PORT ?= /dev/ttyUSB0
STA_PORT ?= /dev/ttyUSB1
FQBN ?= esp32:esp32:esp32
UPLOAD_SPEED ?= 921600
BUILD_PATH ?= .build
BOARD_OPTIONS ?= PartitionScheme=huge_app

.PHONY: compile upload monitor flash ap_compile ap_upload ap_monitor ap_flash sta_compile sta_upload sta_monitor sta_flash

compile:
	arduino-cli compile --fqbn $(FQBN) --board-options $(BOARD_OPTIONS) --build-path $(BUILD_PATH)/$(SKETCH) ./$(SKETCH)

upload:
	arduino-cli upload -p $(PORT) --fqbn $(FQBN) --build-path $(BUILD_PATH)/$(SKETCH) --upload-property upload.speed=$(UPLOAD_SPEED) ./$(SKETCH)

monitor:
	arduino-cli monitor -p $(PORT) --fqbn $(FQBN) --config baudrate=921600

flash: upload

ap_compile:
	$(MAKE) compile SKETCH=esp32_ap

ap_upload:
	$(MAKE) upload SKETCH=esp32_ap PORT=$(AP_PORT)

ap_monitor:
	$(MAKE) monitor PORT=$(AP_PORT)

ap_flash: ap_upload

sta_compile:
	$(MAKE) compile SKETCH=esp32_sta

sta_upload:
	$(MAKE) upload SKETCH=esp32_sta PORT=$(STA_PORT)

sta_monitor:
	$(MAKE) monitor PORT=$(STA_PORT)

sta_flash: sta_upload
