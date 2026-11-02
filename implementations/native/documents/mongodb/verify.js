const products = db.getSiblingDB('storebench').products;
function check(ok, message) { if (!ok) throw new Error(message); }
check(products.countDocuments({}) === 6, 'Expected six products');
check(products.findOne({ id: 'p001' }).name === 'Trail Jacket', 'Product lookup mismatch');
check(JSON.stringify(products.find({ 'attributes.color': 'blue', 'attributes.waterproof': true }, { _id: 0, id: 1 }).sort({ id: 1 }).toArray().map(p => p.id)) === JSON.stringify(['p001', 'p003', 'p005']), 'Nested filter mismatch');
check(products.findOne({ id: 'p002' }).attributes.waterproof === true, 'Partial update mismatch');
const actual = products.aggregate([{ $group: { _id: '$category', count: { $sum: 1 }, total: { $sum: '$price_cents' } } }, { $sort: { _id: 1 } }]).toArray();
check(JSON.stringify(actual) === JSON.stringify([{ _id: 'apparel', count: 2, total: 22800 }, { _id: 'footwear', count: 2, total: 24800 }, { _id: 'gear', count: 2, total: 19800 }]), 'Category aggregation mismatch');
print('MongoDB documents check passed');
