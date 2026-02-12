/*
Carga anuncios dinámicamente desde el backend.
Preparado para futuro consumo de base de datos.
*/

document.addEventListener("DOMContentLoaded", () => {

    fetch("/api/announcements")
        .then(response => response.json())
        .then(data => {

            const container = document.getElementById("announcements-container");

            data.forEach(item => {
                const div = document.createElement("div");
                div.classList.add("card");

                div.innerHTML = `
                    <h3>${item.title}</h3>
                    <p>${item.description}</p>
                    <a href="${item.link}" class="secondary-btn">Ver más</a>
                `;

                container.appendChild(div);
            });

        })
        .catch(error => {
            console.error("Error cargando anuncios:", error);
        });

});
