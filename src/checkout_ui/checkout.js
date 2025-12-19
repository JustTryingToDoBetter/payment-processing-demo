/**
 * Checkout JavaScript
 * 
 * This demonstrates how a payment form would work on the frontend.
 * 
 * Key Security Principles:
 * 1. Card data goes directly to payment gateway (not your server)
 * 2. You receive a token in exchange
 * 3. Token is sent to your server to create the charge
 * 
 * In production, you would use the payment provider's JavaScript SDK:
 * - Stripe.js
 * - Braintree's Drop-in UI
 * - Adyen's Web Components
 */

// Configuration
const CONFIG = {
    // API endpoint for tokenization (would be payment gateway in production)
    tokenizeEndpoint: 'http://localhost:8080/v1/tokens',
    
    // API endpoint for charges (your server)
    chargeEndpoint: 'http://localhost:8080/v1/charges',
    
    // API key (in production, this would be a publishable key, not secret)
    apiKey: 'sk_test_demo123456789',
    
    // Order total in cents
    orderTotal: 11470
};

// DOM Elements
const form = document.getElementById('payment-form');
const cardNumberInput = document.getElementById('card-number');
const cardExpiryInput = document.getElementById('card-expiry');
const cardCvvInput = document.getElementById('card-cvv');
const cardNameInput = document.getElementById('card-name');
const cardBrandDisplay = document.getElementById('card-brand');
const submitButton = document.getElementById('submit-button');
const buttonText = document.getElementById('button-text');
const buttonSpinner = document.getElementById('button-spinner');
const errorDisplay = document.getElementById('payment-errors');
const successMessage = document.getElementById('success-message');
const threedsModal = document.getElementById('threeds-modal');

// =============================================================================
// Card Number Formatting & Detection
// =============================================================================

/**
 * Detect card brand from number prefix (BIN)
 */
function detectCardBrand(number) {
    const cleaned = number.replace(/\s/g, '');
    
    if (/^4/.test(cleaned)) return 'visa';
    if (/^5[1-5]/.test(cleaned)) return 'mastercard';
    if (/^3[47]/.test(cleaned)) return 'amex';
    if (/^6(?:011|5)/.test(cleaned)) return 'discover';
    
    return null;
}

/**
 * Get card brand display
 */
function getCardBrandEmoji(brand) {
    const brands = {
        'visa': '💳 Visa',
        'mastercard': '💳 Mastercard',
        'amex': '💳 Amex',
        'discover': '💳 Discover'
    };
    return brands[brand] || '';
}

/**
 * Format card number with spaces
 */
function formatCardNumber(value) {
    const cleaned = value.replace(/\s/g, '').replace(/\D/g, '');
    const groups = cleaned.match(/.{1,4}/g) || [];
    return groups.join(' ').substr(0, 19);
}

/**
 * Format expiry date as MM/YY
 */
function formatExpiry(value) {
    const cleaned = value.replace(/\D/g, '');
    if (cleaned.length >= 2) {
        return cleaned.substr(0, 2) + '/' + cleaned.substr(2, 2);
    }
    return cleaned;
}

// =============================================================================
// Luhn Validation
// =============================================================================

/**
 * Validate card number using Luhn algorithm
 * This is a basic checksum validation
 */
function validateLuhn(number) {
    const cleaned = number.replace(/\s/g, '');
    
    if (!/^\d+$/.test(cleaned)) return false;
    
    let sum = 0;
    let isEven = false;
    
    for (let i = cleaned.length - 1; i >= 0; i--) {
        let digit = parseInt(cleaned[i], 10);
        
        if (isEven) {
            digit *= 2;
            if (digit > 9) digit -= 9;
        }
        
        sum += digit;
        isEven = !isEven;
    }
    
    return sum % 10 === 0;
}

// =============================================================================
// Input Event Handlers
// =============================================================================

cardNumberInput.addEventListener('input', (e) => {
    // Format the number
    e.target.value = formatCardNumber(e.target.value);
    
    // Detect and display brand
    const brand = detectCardBrand(e.target.value);
    cardBrandDisplay.textContent = getCardBrandEmoji(brand);
    
    // Visual validation
    const cleaned = e.target.value.replace(/\s/g, '');
    if (cleaned.length >= 13) {
        if (validateLuhn(cleaned)) {
            e.target.classList.remove('invalid');
            e.target.classList.add('valid');
        } else {
            e.target.classList.remove('valid');
            e.target.classList.add('invalid');
        }
    } else {
        e.target.classList.remove('valid', 'invalid');
    }
});

cardExpiryInput.addEventListener('input', (e) => {
    e.target.value = formatExpiry(e.target.value);
});

cardCvvInput.addEventListener('input', (e) => {
    e.target.value = e.target.value.replace(/\D/g, '').substr(0, 4);
});

// =============================================================================
// Form Submission
// =============================================================================

form.addEventListener('submit', async (e) => {
    e.preventDefault();
    
    // Clear previous errors
    hideError();
    
    // Validate inputs
    const validation = validateForm();
    if (!validation.valid) {
        showError(validation.message);
        return;
    }
    
    // Show loading state
    setLoading(true);
    
    try {
        // Step 1: Tokenize the card
        // In production, this would go directly to the payment gateway
        // Your server never sees the actual card data
        console.log('Step 1: Tokenizing card...');
        const token = await tokenizeCard();
        console.log('Token received:', token.id);
        
        // Step 2: Check if 3DS is required
        // (Simulated - real implementation would check token response)
        const cardNumber = cardNumberInput.value.replace(/\s/g, '');
        if (cardNumber.startsWith('4000002760')) {
            console.log('3DS required, showing authentication...');
            await handle3DSecure();
        }
        
        // Step 3: Create charge using the token
        // This goes to YOUR server, which then talks to the payment gateway
        console.log('Step 2: Creating charge...');
        const charge = await createCharge(token.id);
        console.log('Charge created:', charge.id);
        
        // Step 4: Handle result
        if (charge.paid) {
            showSuccess(charge.id);
        } else {
            showError(charge.failure_message || 'Payment failed');
        }
        
    } catch (error) {
        console.error('Payment error:', error);
        showError(error.message || 'An error occurred');
    } finally {
        setLoading(false);
    }
});

/**
 * Validate form inputs
 */
function validateForm() {
    const cardNumber = cardNumberInput.value.replace(/\s/g, '');
    const expiry = cardExpiryInput.value;
    const cvv = cardCvvInput.value;
    const name = cardNameInput.value;
    
    if (!cardNumber || cardNumber.length < 13) {
        return { valid: false, message: 'Please enter a valid card number' };
    }
    
    if (!validateLuhn(cardNumber)) {
        return { valid: false, message: 'Invalid card number' };
    }
    
    if (!expiry || expiry.length !== 5) {
        return { valid: false, message: 'Please enter expiry date (MM/YY)' };
    }
    
    const [month, year] = expiry.split('/').map(n => parseInt(n, 10));
    if (month < 1 || month > 12) {
        return { valid: false, message: 'Invalid expiry month' };
    }
    
    const fullYear = 2000 + year;
    const now = new Date();
    const expDate = new Date(fullYear, month - 1);
    if (expDate < now) {
        return { valid: false, message: 'Card has expired' };
    }
    
    if (!cvv || cvv.length < 3) {
        return { valid: false, message: 'Please enter CVV' };
    }
    
    if (!name) {
        return { valid: false, message: 'Please enter cardholder name' };
    }
    
    return { valid: true };
}

/**
 * Tokenize card data
 * 
 * IMPORTANT: In production, this request goes directly to the payment
 * gateway (not through your server). The gateway returns a token that
 * you can safely send to your server.
 */
async function tokenizeCard() {
    const cardNumber = cardNumberInput.value.replace(/\s/g, '');
    const [expMonth, expYear] = cardExpiryInput.value.split('/');
    const cvv = cardCvvInput.value;
    const name = cardNameInput.value;
    
    const response = await fetch(CONFIG.tokenizeEndpoint, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${CONFIG.apiKey}`
        },
        body: JSON.stringify({
            card_number: cardNumber,
            exp_month: parseInt(expMonth, 10),
            exp_year: 2000 + parseInt(expYear, 10),
            cvv: cvv,
            name: name
        })
    });
    
    const data = await response.json();
    
    if (!response.ok) {
        throw new Error(data.error?.message || 'Failed to tokenize card');
    }
    
    return data;
}

/**
 * Create a charge using the token
 * 
 * This request goes to YOUR server. Your server then uses its
 * secret API key to create the charge with the payment gateway.
 */
async function createCharge(tokenId) {
    // Generate idempotency key from order info
    // This prevents duplicate charges if customer double-clicks
    const idempotencyKey = `order_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
    
    const response = await fetch(CONFIG.chargeEndpoint, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${CONFIG.apiKey}`,
            'Idempotency-Key': idempotencyKey
        },
        body: JSON.stringify({
            token: tokenId,
            amount: CONFIG.orderTotal,
            currency: 'usd',
            description: 'Demo Order'
        })
    });
    
    const data = await response.json();
    
    if (!response.ok) {
        throw new Error(data.error?.message || 'Payment failed');
    }
    
    return data;
}

/**
 * Handle 3D Secure authentication
 * 
 * In production, this would:
 * 1. Show an iframe with the bank's authentication page
 * 2. Wait for the customer to complete verification
 * 3. Receive a callback with the result
 */
async function handle3DSecure() {
    return new Promise((resolve) => {
        threedsModal.style.display = 'flex';
        
        // Simulate 3DS completion after verification
        window.complete3DS = () => {
            threedsModal.style.display = 'none';
            resolve();
        };
    });
}

// =============================================================================
// UI Helpers
// =============================================================================

function setLoading(loading) {
    submitButton.disabled = loading;
    buttonText.style.display = loading ? 'none' : 'inline';
    buttonSpinner.style.display = loading ? 'inline-block' : 'none';
}

function showError(message) {
    errorDisplay.textContent = message;
    errorDisplay.style.display = 'block';
}

function hideError() {
    errorDisplay.style.display = 'none';
}

function showSuccess(chargeId) {
    form.style.display = 'none';
    document.querySelector('.order-summary').style.display = 'none';
    document.getElementById('charge-id').textContent = chargeId;
    successMessage.style.display = 'block';
}

// =============================================================================
// Test Card Helpers
// =============================================================================

// For demo purposes - fill in test card data
console.log('%c🔒 Payment Demo', 'font-size: 16px; font-weight: bold;');
console.log('%cTest cards:', 'font-weight: bold;');
console.log('  4242424242424242 - Always succeeds');
console.log('  4000000000009995 - Insufficient funds');
console.log('  4000000000000002 - Card declined');
console.log('  4000002760003184 - 3DS required');
console.log('');
console.log('Use any future date for expiry and any 3 digits for CVV');
