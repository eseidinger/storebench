const database = db.getSiblingDB('storebench');
database.products.drop();
database.products.insertMany([{"id":"p001","name":"Trail Jacket","category":"apparel","price_cents":12900,"stock":12,"attributes":{"color":"blue","size":"M","waterproof":true}},{"id":"p002","name":"City Jacket","category":"apparel","price_cents":9900,"stock":8,"attributes":{"color":"black","size":"L","waterproof":false}},{"id":"p003","name":"Hiking Boots","category":"footwear","price_cents":15900,"stock":5,"attributes":{"color":"blue","size":"42","waterproof":true}},{"id":"p004","name":"Running Shoes","category":"footwear","price_cents":8900,"stock":20,"attributes":{"color":"red","size":"42","waterproof":false}},{"id":"p005","name":"Day Pack","category":"gear","price_cents":7900,"stock":15,"attributes":{"color":"blue","capacity_l":20,"waterproof":true}},{"id":"p006","name":"Travel Pack","category":"gear","price_cents":11900,"stock":7,"attributes":{"color":"green","capacity_l":35,"waterproof":false}}]);
database.products.createIndex({ id: 1 }, { unique: true });
database.products.createIndex({ category: 1 });
database.products.createIndex({ attributes: 1 });
print('Inserted ' + database.products.countDocuments({}) + ' products');
