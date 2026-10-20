import random
import string
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import db, User, Allocation, Application, Payment, Notification

payment_bp = Blueprint('payment', __name__, url_prefix='/api/payment')

@payment_bp.route('/details', methods=['GET'])
@jwt_required()
def get_payment_details():
    user_id = int(get_jwt_identity())
    
    alloc = Allocation.query.filter_by(student_id=user_id).first()
    if not alloc:
        return jsonify({'has_payment': False, 'message': 'No room allocation found for this account.'}), 200

    pmt = Payment.query.filter_by(allocation_id=alloc.id).first()
    if not pmt:
        return jsonify({'has_payment': False, 'message': 'No payment invoice found.'}), 200

    return jsonify({
        'has_payment': True,
        'payment': pmt.to_dict(),
        'allocation': alloc.to_dict()
    }), 200

@payment_bp.route('/pay', methods=['POST'])
@jwt_required()
def execute_simulated_payment():
    user_id = int(get_jwt_identity())
    user = User.query.get(user_id)

    alloc = Allocation.query.filter_by(student_id=user_id).first()
    if not alloc:
        return jsonify({'error': 'No active room allocation found to process payment.'}), 404

    pmt = Payment.query.filter_by(allocation_id=alloc.id).first()
    if not pmt:
        return jsonify({'error': 'Payment record not found.'}), 404

    if pmt.payment_status == 'successful':
        return jsonify({'error': 'Payment for this allocation has already been completed.'}), 400

    data = request.get_json() or {}
    payment_method = data.get('payment_method', 'simulated_upi')

    now = datetime.now(timezone.utc)
    rand_tx = ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))
    tx_id = f"SWTXN-{rand_tx}"
    rec_num = f"SW-REC-{datetime.now().year}-" + ''.join(random.choices(string.digits, k=6))

    # Update Payment
    pmt.payment_status = 'successful'
    pmt.transaction_id = tx_id
    pmt.receipt_number = rec_num
    pmt.payment_method = payment_method
    pmt.updated_at = now

    # Update Allocation & Application
    alloc.status = 'payment_completed'
    app_rec = Application.query.get(alloc.application_id)
    if app_rec:
        app_rec.status = 'payment_completed'

    # Send Notification
    notif = Notification(
        user_id=user_id,
        title='Payment Received - Room Booking Confirmed!',
        message=f"Simulated fee payment of ₹{pmt.amount:,.2f} recorded (Receipt: {rec_num}). Allocation is confirmed.",
        type='payment',
        is_read=False,
        created_at=now
    )
    db.session.add(notif)
    db.session.commit()

    return jsonify({
        'message': 'Simulated payment processed successfully!',
        'transaction_id': tx_id,
        'receipt_number': rec_num,
        'payment': pmt.to_dict(),
        'allocation': alloc.to_dict()
    }), 200
