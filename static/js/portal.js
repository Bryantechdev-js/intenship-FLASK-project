(function () {
    const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    const loader = document.querySelector("[data-page-loader]");
    if (loader) {
        const hideLoader = function () {
            loader.classList.add("is-hidden");
            window.setTimeout(function () {
                loader.remove();
            }, 500);
        };

        window.addEventListener("load", hideLoader, { once: true });
        window.setTimeout(hideLoader, 2400);
    }

    const navToggle = document.querySelector("[data-nav-toggle]");
    const nav = document.querySelector("#primary-nav");

    if (navToggle && nav) {
        navToggle.addEventListener("click", function () {
            const isOpen = nav.classList.toggle("is-open");
            navToggle.setAttribute("aria-expanded", String(isOpen));
        });

        nav.querySelectorAll("a").forEach(function (link) {
            link.addEventListener("click", function () {
                nav.classList.remove("is-open");
                navToggle.setAttribute("aria-expanded", "false");
            });
        });
    }

    document.querySelectorAll("[data-dismiss-flash]").forEach(function (button) {
        button.addEventListener("click", function () {
            const flash = button.closest(".flash");
            if (flash) {
                flash.remove();
            }
        });
    });

    if (window.AOS) {
        window.AOS.init({
            duration: 760,
            once: true,
            offset: 72,
            easing: "ease-out-cubic",
            disable: prefersReducedMotion
        });
    }

    const typingElement = document.querySelector("[data-typing]");
    if (typingElement) {
        const words = (typingElement.getAttribute("data-typing-words") || "")
            .split("|")
            .map(function (word) {
                return word.trim();
            })
            .filter(Boolean);

        if (words.length > 0) {
            if (prefersReducedMotion) {
                typingElement.textContent = words[0];
            } else {
                let wordIndex = 0;
                let letterIndex = 0;
                let deleting = false;

                const tick = function () {
                    const currentWord = words[wordIndex];
                    const visibleText = currentWord.slice(0, letterIndex);
                    typingElement.textContent = visibleText;

                    if (!deleting && letterIndex < currentWord.length) {
                        letterIndex += 1;
                        window.setTimeout(tick, 95);
                        return;
                    }

                    if (!deleting && letterIndex === currentWord.length) {
                        deleting = true;
                        window.setTimeout(tick, 1200);
                        return;
                    }

                    if (deleting && letterIndex > 0) {
                        letterIndex -= 1;
                        window.setTimeout(tick, 45);
                        return;
                    }

                    deleting = false;
                    wordIndex = (wordIndex + 1) % words.length;
                    window.setTimeout(tick, 260);
                };

                tick();
            }
        }
    }

    const video = document.querySelector("[data-hero-video]");
    const videoToggle = document.querySelector("[data-video-toggle]");
    const poster = document.querySelector("[data-hero-poster]");

    function showPosterFallback() {
        if (video) {
            video.pause();
            video.hidden = true;
        }
        if (poster) {
            poster.hidden = false;
        }
        if (videoToggle) {
            videoToggle.hidden = true;
        }
    }

    if (video) {
        if (prefersReducedMotion) {
            showPosterFallback();
        } else {
            video.play().catch(function () {
                showPosterFallback();
            });
        }

        video.addEventListener("error", function () {
            showPosterFallback();
        });
    }

    if (video && videoToggle) {
        videoToggle.addEventListener("click", function () {
            if (video.paused) {
                video.play().then(function () {
                    videoToggle.textContent = "Pause video";
                }).catch(function () {
                    videoToggle.textContent = "Play video";
                });
            } else {
                video.pause();
                videoToggle.textContent = "Play video";
            }
        });
    }

    document.querySelectorAll("form").forEach(function (form) {
        if (form.matches("[data-form-kind='contact']")) {
            return;
        }
        form.addEventListener("submit", function (event) {
            const submitButton = form.querySelector("button[type='submit']");
            if (!submitButton || prefersReducedMotion) {
                return;
            }
            if (event.defaultPrevented) {
                return;
            }
            if (typeof form.checkValidity === "function" && !form.checkValidity()) {
                return;
            }
            submitButton.classList.add("is-loading");
            submitButton.setAttribute("aria-busy", "true");
        });
    });

    const contactForm = document.querySelector("[data-form-kind='contact']");
    if (contactForm) {
        const escapeUnsafe = function (value) {
            return String(value || "")
                .replace(/[<>]/g, "")
                .replace(/\s+/g, " ")
                .trim();
        };

        const fields = {
            name: {
                input: contactForm.querySelector("#contact_name"),
                error: contactForm.querySelector("#contact-name-error"),
                validate: function (value) {
                    return /^[A-Za-z][A-Za-z '\-.,]{1,79}$/.test(value);
                },
                message: "Enter a valid full name (2-80 chars)."
            },
            email: {
                input: contactForm.querySelector("#contact_email"),
                error: contactForm.querySelector("#contact-email-error"),
                validate: function (value) {
                    return /^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,63}$/.test(value);
                },
                message: "Enter a valid email address."
            },
            subject: {
                input: contactForm.querySelector("#contact_subject"),
                error: contactForm.querySelector("#contact-subject-error"),
                validate: function (value) {
                    return value.length >= 4 && value.length <= 120;
                },
                message: "Subject must be between 4 and 120 characters."
            },
            message: {
                input: contactForm.querySelector("#contact_message"),
                error: contactForm.querySelector("#contact-message-error"),
                validate: function (value) {
                    return value.length >= 20 && value.length <= 1200;
                },
                message: "Message must be between 20 and 1200 characters."
            }
        };

        const setFieldState = function (field, isValid, errorText) {
            if (!field.input || !field.error) {
                return;
            }
            field.input.classList.toggle("is-invalid", !isValid);
            field.input.setAttribute("aria-invalid", String(!isValid));
            if (isValid) {
                field.error.hidden = true;
                field.error.textContent = "";
            } else {
                field.error.hidden = false;
                field.error.textContent = errorText;
            }
        };

        const validateField = function (key) {
            const field = fields[key];
            if (!field || !field.input) {
                return true;
            }
            const sanitized = key === "message"
                ? String(field.input.value || "").replace(/[<>]/g, "").trim()
                : escapeUnsafe(field.input.value);
            field.input.value = sanitized;
            const valid = field.validate(sanitized);
            setFieldState(field, valid, field.message);
            return valid;
        };

        Object.keys(fields).forEach(function (key) {
            const field = fields[key];
            if (!field.input) {
                return;
            }
            field.input.addEventListener("blur", function () {
                validateField(key);
            });
        });

        contactForm.addEventListener("submit", function (event) {
            let hasError = false;

            Object.keys(fields).forEach(function (key) {
                if (!validateField(key)) {
                    hasError = true;
                }
            });

            if (hasError) {
                event.preventDefault();
                const firstInvalid = contactForm.querySelector(".is-invalid");
                if (firstInvalid) {
                    firstInvalid.focus();
                }
                return;
            }

            if (!prefersReducedMotion) {
                const submitButton = contactForm.querySelector("button[type='submit']");
                if (submitButton) {
                    submitButton.classList.add("is-loading");
                    submitButton.setAttribute("aria-busy", "true");
                }
            }
        });
    }
})();
