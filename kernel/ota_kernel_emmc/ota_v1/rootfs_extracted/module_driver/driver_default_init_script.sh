#!/bin/sh

if [ -f /usr/prog/module_driver ]; then
   mount /usr/prog/module_driver/  /module_driver/
fi
sh rmem_manager.sh
sh soc_gpio.sh
sh soc_pwm.sh
sh soc_fb_layer_mixer.sh
sh soc_fb.sh
sh gpio_regulator.sh
sh soc_dtrng.sh
if [ -f /usr/prog/module/lcd.sh ]; then
   sh /usr/prog/module/lcd.sh
else
   sh lcd_kx070.sh
fi
sh soc_i2c.sh
sh keyboard_gpio_add.sh
sh soc_aic.sh
sh soc_icodec.sh
sh soc_adc.sh
sh soc_watchdog.sh
sh x2600_510_icodec_sound_card.sh
