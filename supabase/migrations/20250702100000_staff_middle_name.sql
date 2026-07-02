-- Optional middle name on staff; staff_code generation uses middle initial for disambiguation.

ALTER TABLE rgtime.staff
    ADD COLUMN IF NOT EXISTS middle_name TEXT;

COMMENT ON COLUMN rgtime.staff.middle_name IS
    'Optional legal middle name; used for display and staff_code disambiguation.';
