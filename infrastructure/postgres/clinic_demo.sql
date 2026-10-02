-- Demo "clinic" business database used by the Doctor Appointment template.
-- This is the *customer's* database (separate from the platform database); the
-- agent reaches it only through permission-checked database actions.
-- Idempotent: safe to run repeatedly. Slots are generated relative to today.

CREATE SCHEMA IF NOT EXISTS clinic;
SET search_path TO clinic;

CREATE TABLE IF NOT EXISTS specialties (
    id serial PRIMARY KEY,
    name_ar text NOT NULL,
    name_en text NOT NULL,
    keywords text NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS doctors (
    id serial PRIMARY KEY,
    name_ar text NOT NULL,
    name_en text NOT NULL,
    specialty_id int NOT NULL REFERENCES specialties(id),
    active boolean NOT NULL DEFAULT true
);

CREATE TABLE IF NOT EXISTS patients (
    id serial PRIMARY KEY,
    full_name text NOT NULL,
    phone text NOT NULL UNIQUE,
    date_of_birth date,
    national_id text,          -- sensitive: denied to the agent
    medical_notes text,        -- sensitive: denied to the agent
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS slots (
    id serial PRIMARY KEY,
    doctor_id int NOT NULL REFERENCES doctors(id),
    starts_at timestamp NOT NULL,
    duration_minutes int NOT NULL DEFAULT 30,
    UNIQUE (doctor_id, starts_at)
);

CREATE TABLE IF NOT EXISTS appointments (
    id serial PRIMARY KEY,
    patient_id int NOT NULL REFERENCES patients(id),
    doctor_id int NOT NULL REFERENCES doctors(id),
    slot_id int NOT NULL REFERENCES slots(id),
    status text NOT NULL DEFAULT 'booked' CHECK (status IN ('booked', 'cancelled', 'completed')),
    source text NOT NULL DEFAULT 'ai_agent',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
-- A slot can only hold one active booking: the database is the source of truth.
CREATE UNIQUE INDEX IF NOT EXISTS appointments_one_active_per_slot ON appointments (slot_id) WHERE status = 'booked';

CREATE OR REPLACE FUNCTION clinic.ar_day(d date) RETURNS text LANGUAGE sql IMMUTABLE AS $$
  SELECT (ARRAY['الأحد','الاثنين','الثلاثاء','الأربعاء','الخميس','الجمعة','السبت'])[extract(dow from d)::int + 1]
$$;

CREATE OR REPLACE FUNCTION clinic.ar_time(t time) RETURNS text LANGUAGE sql IMMUTABLE AS $$
  SELECT CASE WHEN extract(hour from t) = 0 THEN '12' WHEN extract(hour from t) > 12
              THEN (extract(hour from t)::int - 12)::text ELSE extract(hour from t)::int::text END
         || CASE WHEN extract(minute from t) > 0 THEN ':' || to_char(t, 'MI') ELSE '' END
         || CASE WHEN extract(hour from t) >= 12 THEN ' مساءً' ELSE ' صباحاً' END
$$;

CREATE OR REPLACE VIEW available_slots AS
SELECT s.id AS slot_id, s.doctor_id, d.name_ar AS doctor_name_ar, d.name_en AS doctor_name_en,
       d.specialty_id, sp.name_ar AS specialty_name_ar, sp.name_en AS specialty_name_en,
       s.starts_at, s.starts_at::date AS slot_date, to_char(s.starts_at, 'HH24:MI') AS slot_time,
       clinic.ar_day(s.starts_at::date) || ' ' || to_char(s.starts_at, 'DD/MM') || ' الساعة ' || clinic.ar_time(s.starts_at::time)
         || ' مع ' || d.name_ar AS label_ar,
       to_char(s.starts_at, 'FMDay DD Mon "at" FMHH12:MI AM') || ' with ' || d.name_en AS label_en
FROM slots s
JOIN doctors d ON d.id = s.doctor_id AND d.active
JOIN specialties sp ON sp.id = d.specialty_id
WHERE s.starts_at > now()
  AND NOT EXISTS (SELECT 1 FROM appointments a WHERE a.slot_id = s.id AND a.status = 'booked');

CREATE OR REPLACE VIEW appointment_details AS
SELECT a.id AS appointment_id, a.patient_id, a.status, a.doctor_id, a.slot_id,
       d.name_ar AS doctor_name_ar, d.name_en AS doctor_name_en, sp.name_ar AS specialty_name_ar,
       sp.name_en AS specialty_name_en, s.starts_at,
       clinic.ar_day(s.starts_at::date) || ' ' || to_char(s.starts_at, 'DD/MM') || ' الساعة ' || clinic.ar_time(s.starts_at::time)
         || ' مع ' || d.name_ar AS label_ar,
       to_char(s.starts_at, 'FMDay DD Mon "at" FMHH12:MI AM') || ' with ' || d.name_en AS label_en
FROM appointments a
JOIN slots s ON s.id = a.slot_id
JOIN doctors d ON d.id = a.doctor_id
JOIN specialties sp ON sp.id = d.specialty_id;

INSERT INTO specialties (id, name_ar, name_en, keywords) VALUES
  (1, 'الجلدية', 'Dermatology', 'جلد جلدية بشرة حبوب skin dermatologist'),
  (2, 'الأسنان', 'Dentistry', 'اسنان سن ضرس تقويم teeth dental dentist'),
  (3, 'الأطفال', 'Pediatrics', 'اطفال طفل ولد بنت kids children pediatrician'),
  (4, 'الباطنية', 'Internal Medicine', 'باطنية باطنه معده سكر ضغط internal'),
  (5, 'العيون', 'Ophthalmology', 'عيون عين نظر eye eyes')
ON CONFLICT (id) DO NOTHING;

INSERT INTO doctors (id, name_ar, name_en, specialty_id) VALUES
  (1, 'د. سارة العتيبي', 'Dr. Sara Alotaibi', 1),
  (2, 'د. خالد الحربي', 'Dr. Khalid Alharbi', 1),
  (3, 'د. منى القحطاني', 'Dr. Mona Alqahtani', 2),
  (4, 'د. أحمد الزهراني', 'Dr. Ahmed Alzahrani', 3),
  (5, 'د. ريم الشهري', 'Dr. Reem Alshehri', 4),
  (6, 'د. فهد الدوسري', 'Dr. Fahad Aldosari', 5)
ON CONFLICT (id) DO NOTHING;

DO $$ BEGIN
  PERFORM setval(pg_get_serial_sequence('clinic.specialties', 'id'), (SELECT max(id) FROM clinic.specialties));
  PERFORM setval(pg_get_serial_sequence('clinic.doctors', 'id'), (SELECT max(id) FROM clinic.doctors));
END $$;

-- Evening clinic: Sun-Thu 16:00-21:00, every 30 minutes, every other slot per doctor, next 60 days.
INSERT INTO slots (doctor_id, starts_at)
SELECT d.id, day::date + interval '16 hours' + n * interval '30 minutes'
FROM doctors d
CROSS JOIN generate_series(current_date + 1, current_date + 60, interval '1 day') AS day
CROSS JOIN generate_series(0, 9) AS n
WHERE extract(dow from day) BETWEEN 0 AND 4
  AND (n + d.id) % 3 = 0
ON CONFLICT DO NOTHING;

INSERT INTO patients (full_name, phone, date_of_birth, national_id, medical_notes) VALUES
  ('محمد عبدالله', '+966500000001', '1990-04-12', '1000000001', 'confidential'),
  ('Fatimah Ali', '+966500000002', '1985-09-30', '1000000002', 'confidential')
ON CONFLICT (phone) DO NOTHING;
