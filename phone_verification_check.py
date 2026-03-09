# Função para detectar página de verificação de telefone
async def check_for_phone_verification(page):
    """Detecta se Amazon está pedindo verificação de telefone"""
    phone_verification_indicators = [
        'text="Add mobile number"',
        'text="Step 1 of 2"',
        ':text("Add mobile number")',
        ':text("Step 1 of 2")',
        'text*="enhance your account security"',
        'text*="add and verify your mobile number"',
        '[name="phoneNumber"]',
        'input[type="tel"]'
    ]
    
    for selector in phone_verification_indicators:
        try:
            await page.wait_for_selector(selector, timeout=2000)
            return True
        except:
            continue
    
    return False
