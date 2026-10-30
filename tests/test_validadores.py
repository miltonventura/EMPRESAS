from clinica.validadores import normalizar_celular, normalizar_dui


def test_normalizar_dui():
    assert normalizar_dui('123456789') == '12345678-9'
    assert normalizar_dui('12345678-9') == '12345678-9'
    assert normalizar_dui('1234-5678') is None
    assert normalizar_dui('') is None


def test_normalizar_celular():
    assert normalizar_celular('71234567') == '7123-4567'
    assert normalizar_celular('+503 7123-4567') == '7123-4567'
    assert normalizar_celular('7123 456') is None
