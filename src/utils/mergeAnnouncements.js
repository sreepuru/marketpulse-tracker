export function mergeAnnouncements(actions, announcements) {

    const merged = [
        ...actions,
        ...announcements
    ];

    // Remove duplicates
    const uniqueMap = new Map();

    merged.forEach(item => {

        const key =
            `${item.symbol}_${item.subject}_${item.caBroadcastDate}`;

        if (!uniqueMap.has(key)) {
            uniqueMap.set(key, item);
        }

    });

    const uniqueData = [...uniqueMap.values()];

    // Latest announcement first
    uniqueData.sort((a, b) => {

        return new Date(b.caBroadcastDate) - new Date(a.caBroadcastDate);

    });

    return uniqueData;

}