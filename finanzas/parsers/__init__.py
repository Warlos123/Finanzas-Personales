"""Parsers por fuente. Todos tienen la firma `parsear(contenido, recibido_en) -> ResultadoParseo`."""

from finanzas.parsers import bcr_email, sinpe_sms

PARSERS = {
    "gmail_bcr": bcr_email.parsear,
    "sms_4066": sinpe_sms.parsear,
}
