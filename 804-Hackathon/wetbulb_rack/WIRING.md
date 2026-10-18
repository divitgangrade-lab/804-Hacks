# Wetbulb rack: wiring (Arduino Uno R3 + HW-131 power module)

Unplug everything while you wire.

## 0. Power: the HW-131 powers the breadboard
The **HW-131** powers every part on the breadboard. The **Arduino gets its power only from the laptop's USB cable**, which also carries the data link to the dashboard.

| Step | Do this |
|---|---|
| 1 | Plug the HW-131 onto one end of the breadboard so its pins go into **both** pairs of power rails (top and bottom). |
| 2 | Check that the HW-131's **+** pins land in the rails marked **+ (red)** and its **−** pins in the rails marked **− (blue)**. Some boards line up backwards, so look closely. |
| 3 | Set **both** of the HW-131's jumpers to **5V** (not 3.3V, not OFF). |
| 4 | Arduino **GND** → **top − rail** |
| 5 | **Top − rail → bottom − rail** with one jumper wire. This makes sure all the grounds are joined. |
| 6 | Arduino **5V** pin → **nothing**. Leave it empty. |

Use the rails like this:
- **Top rails = LOGIC**: LCD, DHT11, joystick
- **Bottom rails = MOTOR**: the fan motor and ULN2003

Keeping the motor on its own rails cuts down on electrical noise that can scramble the LCD.

## 1. DHT11 (temperature + humidity)
| DHT11 pin | To |
|---|---|
| **+ / VCC** | top + rail |
| **− / GND** | top − rail |
| **S / DATA / OUT** | Arduino **D7** |

A bare 4-pin DHT11 (blue box, no board) also needs a 10 kΩ resistor between DATA and VCC. Its pins, left to right with the grid facing you: VCC, DATA, (unused), GND.

## 2. LCD 8x2 (16 pins)
Pin 1 is marked on the board.

| LCD pin | Name | To |
|---|---|---|
| 1 | VSS | top − rail |
| 2 | VDD | top + rail |
| 3 | V0 (contrast) | Arduino **D6** |
| 4 | RS | Arduino **D12** |
| 5 | RW | top − rail |
| 6 | E | Arduino **D11** |
| 7, 8, 9, 10 | D0–D3 | nothing (leave empty) |
| 11 | D4 | Arduino **D5** |
| 12 | D5 | Arduino **D4** |
| 13 | D6 | Arduino **D3** |
| 14 | D7 | Arduino **D2** |
| 15 | A (backlight +) | top + rail, through a **220 Ω** resistor (a direct wire works if you have no resistor) |
| 16 | K (backlight −) | top − rail |

Watch the order: LCD D4 goes to Arduino D5, and LCD D5 goes to Arduino D4. That's correct.

If your LCD has only 14 pins, it has no backlight, so skip pins 15 and 16.

## 3. Fan (a DC motor with a fan blade) + ULN2003
The motor has two leads, and either one can go either way. Swapping them only reverses the spin direction.

**If you have the ULN2003 driver board** (4 LEDs and a white 5-hole socket):

| From | To |
|---|---|
| Board **IN1** | Arduino **D9** |
| Board **−** | bottom − rail |
| Board **+** | bottom + rail |
| Motor **lead 1** | bottom + rail |
| Motor **lead 2** | one hole of the white socket (see below) |

To find the right socket hole, upload the code first. Then put motor lead 2 in one hole and press the Arduino's **RESET** button. The motor spins for about 1 second at every boot, and LED **A** lights at the same time. Try each hole until it spins during that test.

**If you have the bare ULN2003 chip** (16 legs, notch at the top, pin 1 is top-left):

| Chip pin | To |
|---|---|
| 1 (IN1) | Arduino **D9** |
| 8 (GND) | bottom − rail |
| 9 (COM) | bottom + rail |
| 16 (OUT1) | motor **lead 2** |
| motor **lead 1** | bottom + rail |

**If the ULN2003 gets hot or the motor is weak**, double it up: connect **IN2** to **D9** as well, and **OUT2** (chip pin 15, or the next socket hole) to motor lead 2. Two channels share the current.

The HW-095 isn't used.

## 4. Joystick (5 pins)
| Joystick pin | To |
|---|---|
| **GND** | top − rail |
| **+5V** | top + rail |
| **VRx** | Arduino **A0** |
| **VRy** | Arduino **A1** |
| **SW** | Arduino **A2** |

## 5. Turn-on order (important)
1. **Turn on the HW-131 first.** Plug it into power (USB or its round jack) and press its power button. Its LED lights.
2. **Then** plug the Arduino into the laptop. If the Arduino was already on, press its **RESET** button.

If the Arduino starts before the HW-131, the LCD has no power when the code sets it up, and it shows garbage until you press RESET.

## 6. Upload (Arduino IDE)
1. **Tools → Manage Libraries**, search **DHT sensor library**, choose the one **by Adafruit**, click **Install**, then **Install all**. LiquidCrystal and EEPROM come with the IDE.
2. **File → New**, delete everything, and paste the code.
3. **Tools → Board → Arduino AVR Boards → Arduino Uno**
4. **Tools → Port** → the one that says **Arduino Uno** (looks like `/dev/cu.usbmodem…`)
5. Click **Upload** (→). Wait for "Done uploading".

## 7. Test (about 2 minutes)
| Check | You should see |
|---|---|
| Boot | "WETBULB" with a bar filling up, and the motor spinning for ~1 s |
| After 2 s | The status screen: `*COOLING` / `H2O 0.6L` (or `~FREEAIR` in cold air) |
| Joystick left/right | Page title flashes, then that page: STATUS, AIR, WETBLB, WATER, CO2, FOCUS |
| Joystick up/down | FOCUS page: the knob slides between CO2 and H2O |
| Joystick click | `NO APP / CONNECT` (normal until the dashboard is connected) |
| Hold click + push up/down | Contrast changes. It's saved, so it survives a restart. |
| Breathe on the DHT11, or put the damp-sponge cup over it | Within ~10 s, the wet-bulb and water numbers rise and the motor speeds up |
| **Tools → Serial Monitor**, 115200 baud, "Newline" | Lines like `S,23.4,61` every 2 s, and `J,PAGE,2` when you move the joystick |
| Type `L,*RUN NOW,~-24%H2O,200,380,50` and press Enter | The screen shows RUN NOW with a spinning fan icon, and the motor runs |
| Type `L,WAIT 3h,~-24%H2O,0,410,50` and press Enter | The screen shows WAIT and the motor stops |

**Close the Serial Monitor before clicking "Connect rack" in the dashboard.** Only one program can use the port at a time.

## If something's wrong
| Problem | Fix |
|---|---|
| Blank LCD or a row of solid boxes | Press RESET (the HW-131 may have turned on after the Arduino). Then hold the joystick click and push up/down to change contrast. If nothing changes, unplug LCD pin 3 from D6 and connect it to the top − rail instead. |
| LCD shows garbage when the motor starts | Motor noise. Make sure the motor is on the **bottom** rails only. If you have a small 0.1 µF ceramic capacitor, solder or clip it across the motor's two leads. |
| Garbled letters | Recheck LCD pins 11–14 → D5, D4, D3, D2 (in that order), and RS/E → D12/D11 |
| `SENSOR?` / `CHECK D7` | DHT11 DATA is not on D7, or a bare sensor is missing its 10 kΩ resistor |
| Motor hums or twitches but doesn't spin | Change `MIN_RUN_PWM` from 90 to 140 at the top of the code, then upload again |
| Motor never spins | The HW-131 is off, a jumper is on OFF/3.3V, the − rails aren't joined to the Arduino GND, or motor lead 2 is in the wrong socket hole |
| Nothing works and the HW-131 LED is off | Its power button, or a weak USB source. Try a phone charger. |
| Joystick directions backwards | Set `FLIP_X`, `FLIP_Y` or `SWAP_XY` to `true` at the top of the code |
