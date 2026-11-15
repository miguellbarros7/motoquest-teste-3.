from pathlib import Path
import sys

path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('index.html')
s = path.read_text(encoding='utf-8')
start = s.index('function matchFuelStationPrice(station, records) {')
end = s.index('async function fetchFuelPricePage(fuel, page) {',start)
new_match = r'''// Associar preços apenas quando o posto é identificado inequivocamente.
// Nunca associar por marca ou proximidade isoladamente.
function normalizeFuelText(value) {
    return String(value || "")
        .normalize("NFD")
        .replace(/[\u0300-\u036f]/g, "")
        .toUpperCase()
        .replace(/[^A-Z0-9]+/g, " ")
        .trim();
}

function meaningfulFuelTokens(value) {
    const ignored = new Set([
        "POSTO", "POSTOS", "COMBUSTIVEL", "COMBUSTIVEIS", "ABASTECIMENTO",
        "PA", "DE", "DA", "DO", "DOS", "DAS", "A", "O", "LDA", "SA",
        "UNIPESSOAL", "ESTACAO", "SERVICO", "AUTO", "GASOLINA", "GASOLEO"
    ]);
    return normalizeFuelText(value).split(" ").filter(
        token => token.length > 1 && !ignored.has(token)
    );
}

function fuelBrandCompatible(station, record) {
    const a = normalizeFuelBrand(station.brand);
    const b = normalizeFuelBrand(record.brand);
    // A fonte pode identificar o posto como "Genérico" embora a bomba
    // tenha marca própria. Esse caso exige evidência geográfica e nominal.
    return !a || !b || a === b || b === "GENERICO" || a === "GENERICO";
}

function fuelNameEvidence(station, record) {
    const stationNames = [station.name, station.brand];
    const recordNames = [record.name, record.brand];
    const a = new Set(stationNames.flatMap(meaningfulFuelTokens));
    const b = new Set(recordNames.flatMap(meaningfulFuelTokens));
    const recordLocality = normalizeFuelText(record.locality);
    const stationLocality = normalizeFuelText(station.locality);
    const localityMatch = Boolean(stationLocality && recordLocality && (
        stationLocality === recordLocality ||
        stationLocality.includes(recordLocality) ||
        recordLocality.includes(stationLocality)
    ));
    return { shared: [...a].filter(token => b.has(token)).length, localityMatch };
}

function matchFuelStationPrice(station, records) {
    const lat = Number(station.latitude);
    const lng = Number(station.longitude);
    if (station.latitude == null || station.longitude == null ||
        !Number.isFinite(lat) || !Number.isFinite(lng)) return null;

    const matches = [];
    for (const record of records || []) {
        const rLat = Number(record.location?.lat);
        const rLng = Number(record.location?.lng);
        const price = Number(record.price_eur);
        if (record.station_id == null || record.location?.lat == null ||
            record.location?.lng == null || !Number.isFinite(rLat) ||
            !Number.isFinite(rLng) || !Number.isFinite(price) || price <= 0 ||
            !fuelBrandCompatible(station, record)) continue;

        const distance = fuelStationDistanceMeters(lat, lng, rLat, rLng);
        // Coordenadas de fontes distintas podem representar pontos diferentes
        // do mesmo terreno, mas não se deve aceitar um vizinho por engano.
        if (distance > 175) continue;
        const evidence = fuelNameEvidence(station, record);
        const sameBrand = normalizeFuelBrand(station.brand) ===
            normalizeFuelBrand(record.brand);
        const nameConfirmed = evidence.shared > 0 || evidence.localityMatch;
        // Só permitir alguma tolerância sem nome coincidente quando a marca
        // coincide e o ponto geográfico é praticamente idêntico.
        if (!nameConfirmed && !(sameBrand && distance <= 30)) continue;
        matches.push({ ...record, distanceMeters: distance,
            matchStrength: (evidence.shared > 0 ? 3 : 0) +
                (evidence.localityMatch ? 2 : 0) + (sameBrand ? 1 : 0) });
    }
    if (!matches.length) return null;
    // Havendo mais de um identificador oficial elegível, não escolher o
    // primeiro por acaso: mantemos o preço indisponível.
    if (new Set(matches.map(item => String(item.station_id))).size !== 1) {
        return null;
    }
    return matches.sort((a,b) => a.distanceMeters - b.distanceMeters)[0];
}

'''
s = s[:start] + new_match + s[end:]
start=s.index('async function getFuelPricesForStations(stations, district) {')
end=s.index('async function getFuelDistrict(latitude, longitude) {',start)
new_prices = r'''async function getFuelPricesForStations(stations, district) {
    if (!Array.isArray(stations)) return [];
    const [result95, result98] = await Promise.allSettled([
        fetchFuelPricesByDistrict(district, "gasoline_95"),
        fetchFuelPricesByDistrict(district, "gasoline_98")
    ]);
    const records95 = result95.status === "fulfilled" ? result95.value : [];
    const records98 = result98.status === "fulfilled" ? result98.value : [];
    const by95 = new Map(records95.map(record => [String(record.station_id), record]));
    const by98 = new Map(records98.map(record => [String(record.station_id), record]));

    const toPrice = (record, match) => {
        if (!record || !match || !Number.isFinite(Number(record.price_eur)) ||
            Number(record.price_eur) <= 0) return null;
        return { price: Number(record.price_eur),
            updatedAt: record.updated_at || null,
            stationId: record.station_id };
    };

    return stations.map(station => {
        // Um único posto oficial validado é a chave dos dois combustíveis.
        // O segundo combustível só aparece se existir nesse mesmo posto.
        const match95 = matchFuelStationPrice(station, records95);
        const match98 = matchFuelStationPrice(station, records98);
        const candidateIds = new Set([match95?.station_id, match98?.station_id]
            .filter(id => id != null).map(String));
        if (candidateIds.size > 1) {
            return { ...station, fuelPrices: { gasoline95: null, gasoline98: null } };
        }
        const id = [...candidateIds][0];
        return {
            ...station,
            fuelPrices: {
                gasoline95: id ? toPrice(by95.get(id), match95 || match98) : null,
                gasoline98: id ? toPrice(by98.get(id), match95 || match98) : null
            }
        };
    });
}

'''
s=s[:start]+new_prices+s[end:]
path.write_text(s,encoding='utf-8')
print('Updated',path,len(s))
