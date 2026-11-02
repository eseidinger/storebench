const products = db.getSiblingDB('storebench').products;
// All operations use the same six-product starting dataset.
// 1. Read one product, excluding MongoDB's internal identifier.
printjson(products.findOne({ id: 'p001' }, { _id: 0 }));
// 2. Filter on nested attributes, sorted by stable ID.
printjson(products.find({ 'attributes.color': 'blue', 'attributes.waterproof': true }, { _id: 0, id: 1 }).sort({ id: 1 }).toArray());
// 3. Change one nested attribute without replacing the other fields.
printjson(products.updateOne({ id: 'p002' }, { $set: { 'attributes.waterproof': true } }));
// 4. Aggregate by category after the update.
printjson(products.aggregate([
  { $group: { _id: '$category', product_count: { $sum: 1 }, total_price_cents: { $sum: '$price_cents' } } },
  { $project: { _id: 0, category: '$_id', product_count: 1, total_price_cents: 1 } },
  { $sort: { category: 1 } }
]).toArray());
