#include <Wire.h>
#include <Adafruit_PWMServoDriver.h>
#include <ModbusRTU.h>

#define SLAVE_ID 1
#define WINDOW_SERVO_CHANNEL 0   // Canale del servo per la finestra
#define LOCK_SERVO_CHANNEL 1     // Canale del servo per la serratura
#define STEP_DELAY 10   // ms
#define ANGLE_STEP 0.1  // gradi per la finestra
#define LOCK_ANGLE_STEP 1.0  // gradi per la serratura (può muoversi più velocemente)

// Range servo finestra
const float WINDOW_MIN_ANGLE = 77.0;   // gradi - minimo misurato
const float WINDOW_MAX_ANGLE = 135.0;  // gradi

// Range servo serratura
const float LOCK_MIN_ANGLE = 0.0;    // gradi - completamente chiuso
const float LOCK_MAX_ANGLE = 90.0;   // gradi - completamente aperto

// Parametri impulsi servo finestra (calibrati per il range 77-135)
const uint16_t WINDOW_SERVO_MIN = 300;  // Valore ricalibrato per 77 gradi
const uint16_t WINDOW_SERVO_MAX = 480;  // ~2500us (135 gradi)

// Parametri impulsi servo serratura (per range 0-90)
const uint16_t LOCK_SERVO_MIN = 150;  // ~1000us (0 gradi)
const uint16_t LOCK_SERVO_MAX = 450;  // ~2000us (90 gradi)

// Oggetti
ModbusRTU mb;
Adafruit_PWMServoDriver pwm = Adafruit_PWMServoDriver(0x40);

// Variabili globali per servo finestra
volatile float currentWindowAngle = WINDOW_MIN_ANGLE;
volatile float targetWindowAngle = WINDOW_MIN_ANGLE;
volatile bool windowServoInitialized = false;  // True dopo il primo comando Modbus

// Variabili globali per servo serratura
volatile float currentLockAngle = LOCK_MIN_ANGLE;
volatile float targetLockAngle = LOCK_MIN_ANGLE;
volatile bool lockServoInitialized = false;  // True dopo il primo comando Modbus

unsigned long lastStepTime = 0;
uint16_t lastWindowSetpoint = WINDOW_MIN_ANGLE * 10;  // Ultimo setpoint ricevuto
uint16_t lastLockSetpoint = LOCK_MIN_ANGLE * 10;  // Ultimo setpoint ricevuto

// Converte angolo in valore PWM per il servo finestra
uint16_t windowAngleToPulse(float angle) {
  float limitedAngle = constrain(angle, WINDOW_MIN_ANGLE, WINDOW_MAX_ANGLE);
  return map(limitedAngle * 10, 
            WINDOW_MIN_ANGLE * 10, 
            WINDOW_MAX_ANGLE * 10, 
            WINDOW_SERVO_MIN, 
            WINDOW_SERVO_MAX);
}

// Converte angolo in valore PWM per il servo serratura
uint16_t lockAngleToPulse(float angle) {
  float limitedAngle = constrain(angle, LOCK_MIN_ANGLE, LOCK_MAX_ANGLE);
  return map(limitedAngle * 10, 
            LOCK_MIN_ANGLE * 10, 
            LOCK_MAX_ANGLE * 10, 
            LOCK_SERVO_MIN, 
            LOCK_SERVO_MAX);
}

void setup() {
  // Setup Modbus
  Serial.begin(115200, SERIAL_8N1);
  mb.begin(&Serial);
  mb.slave(SLAVE_ID);

  // Registri holding (16-bit):
  // 0: angolo richiesto finestra (x10)
  // 1: angolo attuale finestra (x10)
  // 2: angolo richiesto serratura (x10)
  // 3: angolo attuale serratura (x10)
  mb.addHreg(0, WINDOW_MIN_ANGLE * 10);
  mb.addHreg(1, WINDOW_MIN_ANGLE * 10);
  mb.addHreg(2, LOCK_MIN_ANGLE * 10);
  mb.addHreg(3, LOCK_MIN_ANGLE * 10);

  // Setup PCA9685
  pwm.begin();
  pwm.setPWMFreq(50);  // 50Hz per servo standard

  // NON forzare i servo alle posizioni iniziali!
  // Lascia che il loop faccia il ramping graduale per evitare
  // movimenti bruschi dopo un reset/riavvio.
  // I target sono già impostati ai valori minimi dalle variabili globali.
  // Il servo si muoverà gradualmente verso il target nel loop.

  delay(100);  // Breve attesa per stabilizzare il PCA9685
}

void updateWindowServo() {
  // Leggi angolo richiesto dal registro (già in gradi x10)
  uint16_t requestedAngle_x10 = mb.Hreg(0);
  float requestedAngle = (float)requestedAngle_x10 / 10.0;

  // Rileva se è arrivato un nuovo setpoint via Modbus
  if (requestedAngle_x10 != lastWindowSetpoint) {
    lastWindowSetpoint = requestedAngle_x10;

    // Primo comando dopo reset: inizializza currentAngle al target
    // per evitare ramping da una posizione sconosciuta
    if (!windowServoInitialized) {
      currentWindowAngle = constrain(requestedAngle, WINDOW_MIN_ANGLE, WINDOW_MAX_ANGLE);
      windowServoInitialized = true;
      pwm.setPWM(WINDOW_SERVO_CHANNEL, 0, windowAngleToPulse(currentWindowAngle));
      mb.Hreg(1, (uint16_t)(currentWindowAngle * 10));
      return;
    }
  }

  // Non muovere il servo finché non è inizializzato
  if (!windowServoInitialized) {
    return;
  }

  // Verifica che l'angolo sia nel range valido
  targetWindowAngle = constrain(requestedAngle, WINDOW_MIN_ANGLE, WINDOW_MAX_ANGLE);

  // Movimento graduale verso il target
  if (abs(targetWindowAngle - currentWindowAngle) > ANGLE_STEP) {
    if (targetWindowAngle > currentWindowAngle) {
      currentWindowAngle += ANGLE_STEP;
    } else {
      currentWindowAngle -= ANGLE_STEP;
    }

    // Aggiorna posizione servo
    pwm.setPWM(WINDOW_SERVO_CHANNEL, 0, windowAngleToPulse(currentWindowAngle));
  }

  // Aggiorna registro posizione attuale
  mb.Hreg(1, (uint16_t)(currentWindowAngle * 10));
}

void updateLockServo() {
  // Leggi angolo richiesto dal registro (già in gradi x10)
  uint16_t requestedAngle_x10 = mb.Hreg(2);
  float requestedAngle = (float)requestedAngle_x10 / 10.0;

  // Rileva se è arrivato un nuovo setpoint via Modbus
  if (requestedAngle_x10 != lastLockSetpoint) {
    lastLockSetpoint = requestedAngle_x10;

    // Primo comando dopo reset: inizializza currentAngle al target
    if (!lockServoInitialized) {
      currentLockAngle = constrain(requestedAngle, LOCK_MIN_ANGLE, LOCK_MAX_ANGLE);
      lockServoInitialized = true;
      pwm.setPWM(LOCK_SERVO_CHANNEL, 0, lockAngleToPulse(currentLockAngle));
      mb.Hreg(3, (uint16_t)(currentLockAngle * 10));
      return;
    }
  }

  // Non muovere il servo finché non è inizializzato
  if (!lockServoInitialized) {
    return;
  }

  // Verifica che l'angolo sia nel range valido
  targetLockAngle = constrain(requestedAngle, LOCK_MIN_ANGLE, LOCK_MAX_ANGLE);

  // Movimento graduale verso il target (più veloce della finestra)
  if (abs(targetLockAngle - currentLockAngle) > LOCK_ANGLE_STEP) {
    if (targetLockAngle > currentLockAngle) {
      currentLockAngle += LOCK_ANGLE_STEP;
    } else {
      currentLockAngle -= LOCK_ANGLE_STEP;
    }

    // Aggiorna posizione servo
    pwm.setPWM(LOCK_SERVO_CHANNEL, 0, lockAngleToPulse(currentLockAngle));
  }

  // Aggiorna registro posizione attuale
  mb.Hreg(3, (uint16_t)(currentLockAngle * 10));
}

void loop() {
  // Gestione Modbus
  mb.task();
  
  // Aggiorna posizione servo ogni STEP_DELAY millisecondi
  if (millis() - lastStepTime >= STEP_DELAY) {
    lastStepTime = millis();
    
    // Aggiorna entrambi i servo
    updateWindowServo();
    updateLockServo();
  }
  
  yield();
}
