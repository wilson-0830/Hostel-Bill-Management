// 付款按钮点击事件
document.querySelectorAll('.pay-btn').forEach(btn => {
    btn.addEventListener('click', function() {
        const itemId = this.dataset.itemId;
        showPaymentModal(itemId);
    });
});

// 显示付款弹窗
function showPaymentModal(itemId) {
    fetch(`/api/payment/items/${itemId}/methods`)
        .then(response => response.json())
        .then(methods => {
            // 填充收款方式
            const methodsContainer = document.querySelector('.payment-methods');
            methodsContainer.innerHTML = methods.map(method => `
                <div class="method">
                    ${method.qr_code_url ? `<img src="${method.qr_code_url}" alt="${method.method_type}二维码">` : ''}
                    <p>${method.method_type}账号: ${method.account_info}</p>
                </div>
            `).join('');
            
            // 显示弹窗
            document.getElementById('payment-modal').style.display = 'block';
        });
}

// 确认付款
document.querySelector('.confirm-btn').addEventListener('click', function() {
    const fileInput = document.getElementById('proof-upload');
    const formData = new FormData();
    formData.append('proof', fileInput.files[0]);
    
    fetch('/api/payment/complete', {
        method: 'POST',
        body: formData
    })
    .then(response => response.json())
    .then(data => {
        alert('付款成功!');
        closeModal();
        // 刷新页面或更新状态
    });
});

<!-- templates/payment_page.html (if you have one) -->
{% extends "base.html" %}

{% block scripts %}
<script src="{{ url_for('static', filename='js/payer.js') }}"></script>
{% endblock %}