// Рендер на каждый запрос: каталог всегда свежий, у инстанса нет своего кеша.
export const dynamic = "force-dynamic";

type Product = { id: number; title: string; image_url: string };

async function getProducts(): Promise<Product[]> {
  const base = process.env.INTERNAL_API_URL ?? "http://nginx";
  const res = await fetch(`${base}/api/products`, { cache: "no-store" });
  if (!res.ok) throw new Error(`API ${res.status}`);
  return res.json();
}

export default async function CatalogPage() {
  const products = await getProducts();
  return (
    <main>
      <h1>Каталог</h1>
      {products.length === 0 ? (
        <p>Товаров пока нет.</p>
      ) : (
        <ul>
          {products.map((p) => (
            <li key={p.id}>
              <img src={p.image_url} alt={p.title} width={200} />
              <div>{p.title}</div>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
