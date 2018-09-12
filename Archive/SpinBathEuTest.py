import os
import copy
import bisect
import numpy as np
import matplotlib as mpl
import scipy.signal
import matplotlib.pyplot as plt

mpl.rcParams["savefig.directory"] = "."
np.set_printoptions(precision=7, edgeitems=30, linewidth=100000)
mpl.rcParams.update({'font.size': 24})

def generate_spin_matrices(spin):
    """ Generates the x, y, z spin matrices for an arbitrary spin"""
    if spin == 0:
        return np.array((0,)), np.array((0,)), np.array((0,))

    # Dimension of spin matrices of a given spin
    dim = int(2 * spin + 1)
    # Generates a descending list from spin to -spin in steps of -1
    desc = np.arange(spin, -spin-1, -1)

    # Create a template for the spin matrices
    sx = np.zeros((dim, dim), dtype=complex)
    sy = np.zeros((dim, dim), dtype=complex)
    sz = np.zeros((dim, dim), dtype=complex)

    # Generate the spin matrices using the formula
    # http://easyspin.org/documentation/spinoperators.html
    for row in range(dim):
        sz[row, row] = desc[row]

        if row == 0:
            sx[row, row+1] = 1/2*np.sqrt(spin*(spin+1)-desc[row]*desc[row+1])
            sy[row, row+1] = -(1j/2)*np.sqrt(spin*(spin+1)-desc[row]*desc[row+1])
        elif row == dim-1:
            sx[row, row-1] = 1/2*np.sqrt(spin*(spin+1)-desc[row]*desc[row-1])
            sy[row, row-1] = (1j/2)*np.sqrt(spin*(spin+1)-desc[row]*desc[row-1])
        else:
            sx[row, row+1] = 1/2*np.sqrt(spin*(spin+1)-desc[row]*desc[row+1])
            sx[row, row-1] = 1/2*np.sqrt(spin*(spin+1)-desc[row]*desc[row-1])
            sy[row, row+1] = -(1j/2)*np.sqrt(spin*(spin+1)-desc[row]*desc[row+1])
            sy[row, row-1] = (1j/2)*np.sqrt(spin*(spin+1)-desc[row]*desc[row-1])

    return sx, sy, sz

class Neighbour:
    def __init__(self, disp_vector, spinH, g_n_host, element):
        self.disp_vector = 10**-10 * np.array(disp_vector)
        self.R = np.linalg.norm(self.disp_vector)
        self.spinH = spinH
        self.multH = int(2*spinH+1)
        self.g_n_host = g_n_host
        self.element = element

        self.Hx, self.Hy, self.Hz = generate_spin_matrices(self.spinH)
        self.H = np.array([self.Hx, self.Hy, self.Hz])
        self.Hv3 = self.H.reshape((3, self.multH**2))

class SpinSystem:

    mu_b = 9.2740100*10**-24 # Bohr Magneton (J/T)
    h = 6.62607004*10**-34   # Planck's constant (J s)
    beta_el = mu_b / (h * 10**9) # Bohr Magneton in GHz/T

    mu_n = 5.0507837*10**-27 # Nuclear Magneton (J/T)
    beta_n = mu_n / (h * 10**9) # Nuclear Magneton in GHz/T

    def unit_vector(self, theta, phi):
        return np.array([ np.sin(theta) * np.cos(phi),
                          np.sin(theta) * np.sin(phi),    
                          np.cos(theta)])

    def set_vector(self, disp_vector):
        self.__init__(self.spinS, self.spinI, self.g_gs, self.g_es, self.A_gs, self.A_es, self.g_n_rei, self.g_n_host, self.spinH, disp_vector)

    def __init__(self, spinS, spinI, g_gs, g_es, A_gs, A_es, g_n_rei, neighbours_list):
        # spinS = Electron spin, spinI = Nuclear spin, spinH = Nuclear spin of host atom
        self.spinS = spinS
        self.spinI = spinI

        # gs = ground state, es = excited state
        # g = electronic zeeman coefficients (3x3 matrix)
        # g_n = REI Nuclear g coefficient (isotropic)
        # g_n_host = Nuclear magnetic moment coefficient of host atom
        self.g_gs = g_gs
        self.g_es = g_es
        self.g_n_rei = g_n_rei

        # A = Hyperfine coefficients (3x3 matrix)
        self.A_gs = A_gs
        self.A_es = A_es

        # Multiplicities of the spin dimensions
        self.multS = int(2*self.spinS+1)
        self.multI = int(2*self.spinI+1)

        # Populate the spin matrices 
        self.sx, self.sy, self.sz = generate_spin_matrices(self.spinS)
        # Concatenate them together. Dimensions: 3 x multS x multS
        self.S = np.array([self.sx, self.sy, self.sz])
        # Convert to a 3D vector with dimensions 3 x multS^2
        self.Sv3 = self.S.reshape((3, self.multS**2))

        # Do the same for the nuclear spin
        self.Ix, self.Iy, self.Iz = generate_spin_matrices(self.spinI)
        self.I = np.array([self.Ix, self.Iy, self.Iz])
        self.Iv3 = self.I.reshape((3, self.multI**2))

        self.neighbours_input = neighbours_list 
        # Take the list of raw inputs and make it into a list of Neighbour objects
        self.neighbours = [Neighbour(*neigh) for neigh in self.neighbours_input]
        self.neighbours_string = "".join([neigh.element for neigh in self.neighbours])

        # Hamiltonian currently consists of only the hyperfine and SHF pieces 
        # since they are independent of the B field.
        self.initialize_HHF()
        self.initialize_SHF()
        self.reset_ham()

        # # Update list of energy levels for each state
        self.calc_energies()

    def reset_ham(self):
        """ Sets the Hamiltonian to consist of only the field independent hyperfine 
        and superhyperfine parts. """

        self.H_gs = copy.deepcopy(self.HHF_gs + self.H_SHF_gs)
        self.H_es = copy.deepcopy(self.HHF_es + self.H_SHF_es)

    def initialize_HHF(self):
        # Compute the hyperfine Hamiltonian by I @ A @ S for the ground state
        # Reshape S from a column matrix of 3 multS x multS matrices to become 3 rows and multS^2 columns
        # This lets to dot with A which is a 3x3 matrix. We then immediately reshape back.
        # Then we take the dot product with I by kronecker product componentwise and sum.
        self.HHF_gs = (self.A_gs @ self.Sv3).reshape((3, self.multS, self.multS))
        # self.HHF_gs = sum(np.kron(self.I[i], self.HHF_gs[i]) for i in range(3))
        self.HHF_gs = sum(self.S[i] @ self.HHF_gs[i] for i in range(3))
        # Used HHF to represent the quadrupole interaction instead (TODO)

        # Expand into the host nucleus space
        for neigh in self.neighbours: 
            self.HHF_gs = np.kron(self.HHF_gs, np.identity(neigh.multH))

        # Repeat for the excited state
        self.HHF_es = (self.A_es @ self.Sv3).reshape((3, self.multS, self.multS))
        self.HHF_es = sum(np.kron(self.I[i], self.HHF_es[i]) for i in range(3))
        # Expand into the host nucleus space
        for neigh in self.neighbours: 
            self.HHF_es = np.kron(self.HHF_es, np.identity(neigh.multH))

    def initialize_SHF(self):
        # mu = mu_b * g * S
        # Use v3 so that we can take the product with the 3x3 g matrix
        # Then reshape so that we get back our column 3 x (multS x multS) 
        mu_REI_gs = -(self.mu_b * self.g_gs @ self.Sv3).reshape((3, self.multS, self.multS)) 
        mu_REI_es = -(self.mu_b * self.g_es @ self.Sv3).reshape((3, self.multS, self.multS))
        # Reshape both back to v3 since we need another dot product, this time with R
        mu_REI_gs_v3 = mu_REI_gs.reshape((3, self.multS**2))
        mu_REI_es_v3 = mu_REI_es.reshape((3, self.multS**2))

        # First term is (mu_REI)dot(mu_host)/R^3
        first_term_gs = 0
        first_term_es = 0
        # Second term is 3(mu_REI dot R)(mu_host dot R)/R^5
        second_term_gs = 0
        second_term_es = 0

        for neigh_idx, neigh in enumerate(self.neighbours):

            mu_host = self.mu_n * neigh.g_n_host * neigh.H
            # Reshape back to v3 since we need another dot product later with R
            mu_host_v3 = mu_host.reshape((3, neigh.multH**2))

            # Do the dot product of mu_REI dot mu_host but with intervening identities
            # for the REI nuclear space + spectator host nuclei
            for i in range(3):
                gs_term = np.kron(mu_REI_gs[i], np.identity(self.multI))
                es_term = np.kron(mu_REI_es[i], np.identity(self.multI))

                for inner_neigh_idx, inner_neigh in enumerate(self.neighbours):
                    if inner_neigh_idx == neigh_idx:
                        gs_term = np.kron(gs_term, mu_host[i])
                        es_term = np.kron(es_term, mu_host[i])
                    else:
                        gs_term = np.kron(gs_term, np.identity(inner_neigh.multH))
                        es_term = np.kron(es_term, np.identity(inner_neigh.multH))

                first_term_gs += gs_term / neigh.R**3
                first_term_es += es_term / neigh.R**3

            # Take the dot product then reshape back
            dot_REI_gs = neigh.disp_vector.dot(mu_REI_gs_v3).reshape((self.multS, self.multS))
            dot_REI_es = neigh.disp_vector.dot(mu_REI_es_v3).reshape((self.multS, self.multS))
            dot_host = neigh.disp_vector.dot(mu_host_v3).reshape((neigh.multH, neigh.multH))
            # Expand into the REI nuclear space first
            dot_REI_gs = np.kron(dot_REI_gs, np.identity(self.multI))
            dot_REI_es = np.kron(dot_REI_es, np.identity(self.multI))

            # Second term is 3(mu_REI dot R)(mu_host dot R)/R^5
            for inner_neigh_idx, inner_neigh in enumerate(self.neighbours):
                if inner_neigh_idx == neigh_idx:
                    dot_REI_gs = np.kron(dot_REI_gs, dot_host)
                    dot_REI_es = np.kron(dot_REI_es, dot_host)
                else:
                    dot_REI_gs = np.kron(dot_REI_gs, np.identity(inner_neigh.multH))
                    dot_REI_es = np.kron(dot_REI_es, np.identity(inner_neigh.multH))

            second_term_gs += (3/neigh.R**5) * dot_REI_gs
            second_term_es += (3/neigh.R**5) * dot_REI_es

        # Divide by the constant factor to convert from J to GHz
        # First 10**-7 comes from mu0/4pi
        self.H_SHF_gs = 10**-7 * (first_term_gs - second_term_gs) / (self.h * 10**9)
        self.H_SHF_es = 10**-7 * (first_term_es - second_term_es) / (self.h * 10**9)

    def update_zeeman_ham(self, B, B_theta, B_phi):
        """ Given a (new) value of the magnetic field, compute the new Zeeman
        interaction term in the hamiltonian and then update the hamiltonian. """

        # Convert B into cartesian
        B_vec = B * np.array([  np.sin(B_theta) * np.cos(B_phi),
                                np.sin(B_theta) * np.sin(B_phi),    
                                np.cos(B_theta)])

        # Compute the electronic Zeeman Hamiltonian using beta * B @ g @ S
        HZ_el_gs = (self.beta_el * B_vec @ self.g_gs @ self.Sv3).reshape((self.multS, self.multS))
        HZ_el_es = (self.beta_el * B_vec @ self.g_es @ self.Sv3).reshape((self.multS, self.multS))
        # Expand into the nuclear spin space
        HZ_el_gs = np.kron(HZ_el_gs, np.identity(self.multI))
        HZ_el_es = np.kron(HZ_el_es, np.identity(self.multI))
        # Then expand into the superhyperfine nuclear spin space
        for neigh in self.neighbours: 
            HZ_el_gs = np.kron(HZ_el_gs, np.identity(neigh.multH))
            HZ_el_es = np.kron(HZ_el_es, np.identity(neigh.multH))

        # Do the same for the REI nuclear Zeeman Hamiltonian but there is no 
        # distinction between GS and ES. We assume the nuclear g factor is an 
        # isotropic scalar.
        HZ_n_rei = (self.beta_n * self.g_n_rei * B_vec @ self.Iv3).reshape((self.multI, self.multI))
        # Expand into the electronic spin space
        HZ_n_rei = np.kron(np.identity(self.multS), HZ_n_rei)
        # Expand into the superhyperfine nuclear spin space
        for neigh in self.neighbours: 
            HZ_n_rei = np.kron(HZ_n_rei, np.identity(neigh.multH))

        # Do the same for the nuclear Zeeman Hamiltonian for the host nuclear spin
        HZ_n_host = 0
        for neigh_idx, neigh in enumerate(self.neighbours):
            # Start with a blank template for the S and I spaces
            HZ_n_host_accum = np.kron(np.identity(self.multS), np.identity(self.multI))
            HZ_n_host_term = (self.beta_n * neigh.g_n_host * B_vec @ neigh.Hv3).reshape((neigh.multH, neigh.multH))

            # Iterate through the neighbours and expand into their spaces
            # When it's its own index we cross the actual Zeeman interaction instead
            for inner_neigh_idx, inner_neigh in enumerate(self.neighbours):
                if inner_neigh_idx == neigh_idx:
                    HZ_n_host_accum = np.kron(HZ_n_host_accum, HZ_n_host_term)
                else:
                    HZ_n_host_accum = np.kron(HZ_n_host_accum, np.identity(inner_neigh.multH))

            HZ_n_host += HZ_n_host_accum

        # Reset the Hamiltonian to be only the field-indep HF part and SHF part
        self.reset_ham()
        # Add in the just-computed Zeeman terms
        # Minus for the nuclear terms since U = -mu.B but no minus for electron
        # since the mu we calculated above is actually negative of what it
        # really is.
        self.H_gs += (HZ_el_gs - HZ_n_rei - HZ_n_host)
        self.H_es += (HZ_el_es - HZ_n_rei - HZ_n_host)

    def update_B(self, B, B_theta, B_phi):
        """ Updates the Zeeman Hamiltonian contribution from a newly
        specified B field with magnitude B and directions theta, phi. The Zeeman
        Hamiltonian is then added to the state's Hamiltonian and the energies 
        are updated. """

        # Include the Zeeman part (REI electron + REI nucleus + host nucleus)
        self.update_zeeman_ham(B, B_theta, B_phi)
        # Update energies
        self.calc_energies()

    def calc_energies(self):
        """ Compute energies for the current Hamiltonian and updates state."""

        # Get the ground state eigvals and eigvecs
        eigval_gs, eigvec_gs = np.linalg.eig(self.H_gs)
        # Sort the columns of the eigvecs in increasing size of the eigvals
        self.E_gs = sorted(eigval_gs)
        self.eigvec_gs = eigvec_gs[:, np.argsort(eigval_gs)]

        # Do the same for the excited state
        eigval_es, eigvec_es = np.linalg.eig(self.H_es)
        # Sort the columns of the eigvecs in increasing size of the eigvals
        self.E_es = sorted(eigval_es)
        self.eigvec_es = eigvec_es[:, np.argsort(eigval_es)]

    def energies(self, state, B=None, B_theta=None, B_phi=None):
        """ Returns energies of a system with the hyperfine interaction and 
        electronic Zeeman interaction. Optional to provide a B field to update 
        before returning. """
        
        if B is not None and B_theta is not None and B_phi is not None:
            self.update_B(B, B_theta, B_phi)

        if state == 'gs':
            return self.E_gs
        elif state == 'es':
            return self.E_es
        else:
            raise Exception

    def spin_transitions(self, B=None, B_theta=None, B_phi=None):
        """ Computes the transitions wit1hin each energy level. Optional to 
        provide a B field to update before computing. Currently it 
        cannot distinguish between the splitting due to hyperfine and those
        due to Zeeman effect. TODO (?) """

        if B is not None and B_theta is not None and B_phi is not None:
            self.update_B(B, B_theta, B_phi)

        gs_transitions = []
        es_transitions = []

        for i in range(len(self.E_es)):
            for j in range(i+1, len(self.E_gs)):
                gs_transitions.append((self.E_gs[j]-self.E_gs[i], (1,1,1))) # 1 is a placeholder for the transition strength
        for i in range(len(self.E_es)):
            for j in range(i+1, len(self.E_es)):
                es_transitions.append((self.E_es[j]-self.E_es[i], (1,1,1)))
        return [gs_transitions, es_transitions]

    def optical_transitions(self, B=None, B_theta=None, B_phi=None, compute_strengths=False):
        """ Computes the transitions between the energy levels. Optional to
        provide a B field to update before computing. """

        if B is not None and B_theta is not None and B_phi is not None:
            self.update_B(B, B_theta, B_phi)

        transitions = []

        for idx_g, e_g in enumerate(self.E_gs):
            for idx_e, e_e in enumerate(self.E_es):
                if compute_strengths:
                    transitions.append((e_e-e_g, self.transition_strength(self.eigvec_gs[:, idx_g], self.eigvec_es[:, idx_e]), (idx_g, idx_e)))
                else:
                    transitions.append((e_e-e_g, None, (idx_g, idx_e)))
        return transitions

    def superhyperfine_levels(self, state, B=None, B_theta=None, B_phi=None):
        """ Looks at the lower electronic zeeman branch of the ground state to 
        look at the superhyperfine energy splittings. Returns the energy of the 
        doublet's upper and lower levels relative to their average as well as 
        the energy gap. """

        if B is not None and B_theta is not None and B_phi is not None:
            self.update_B(B, B_theta, B_phi)

        # Pick the lowest and 2nd lowest energy levels and assume that these
        # represent the energy splitting of the lowest energy state due to 
        # the superhyperfine interaction. 
        low = self.energies(state, B, B_theta, B_phi)[0]
        up = self.energies(state, B, B_theta, B_phi)[1]
        avg = (low + up) / 2

        # Convert from GHz to KHz since this is really small
        lower = (low - avg)  * 10**6
        upper = (up - avg) * 10**6
        diff = (up - low) * 10**6

        # Look at the highest 2 states instead
        low2 = self.energies(state, B, B_theta, B_phi)[-2]
        up2 = self.energies(state, B, B_theta, B_phi)[-1]
        avg2 = (low2 + up2) / 2

        # Convert from GHz to KHz since this is really small
        lower2 = (low2 - avg2)  * 10**6
        upper2 = (up2 - avg2) * 10**6
        diff2 = (up2 - low2) * 10**6

        return lower, upper, diff, lower2, upper2, diff2

    def branching_contrast(self, B=None, B_theta=None, B_phi=None, stated_levels=None):
        """ Computes the branching contrast of the system (given its current 
        displacement vector of the host atom) using the formula given in Car. """
        if B is not None and B_theta is not None and B_phi is not None:
            self.update_B(B, B_theta, B_phi)

        bigSx = 2*np.kron(np.kron(self.sx, np.identity(self.multI)), np.identity(self.multH))
        bigSy = 2*np.kron(np.kron(self.sy, np.identity(self.multI)), np.identity(self.multH))
        bigSz = 2*np.kron(np.kron(self.sz, np.identity(self.multI)), np.identity(self.multH))

        if stated_levels is None:
            gs_lower = self.eigvec_gs[:, 0]
            gs_upper = self.eigvec_gs[:, 1]
            es_lower = self.eigvec_es[:, 0]
        else:
            i, j, k = stated_levels
            gs_lower = self.eigvec_gs[:, i]
            gs_upper = self.eigvec_gs[:, j]
            es_lower = self.eigvec_es[:, k]

        # Overlap while enclosing the Sx, Sy, Sz matrices
        r_23_S_x = abs(gs_upper.conjugate() @ bigSx @ es_lower.T)**2
        r_13_S_x = abs(gs_lower.conjugate() @ bigSx @ es_lower.T)**2

        RS_x = r_23_S_x / r_13_S_x
        rho_S_x = 4 * RS_x / (1 + RS_x)**2

        return r_23_S_x, r_13_S_x, RS_x, rho_S_x, gs_lower, gs_upper, es_lower

    def transition_strength(self, initial, final):
        """ Computes the transition strength for two eigenvectors initial and
        final for the 3 possible polarisation axes. """

        # Transition operator for the 3 axes (expanded into REI nuclear)
        bigSx = 2*np.kron(self.sx, np.identity(self.multI))
        bigSy = 2*np.kron(self.sy, np.identity(self.multI))
        bigSz = 2*np.kron(self.sz, np.identity(self.multI))
        # Expand into host spaces
        for neigh in self.neighbours:
            bigSx = np.kron(bigSx, np.identity(neigh.multH))
            bigSy = np.kron(bigSy, np.identity(neigh.multH))
            bigSz = np.kron(bigSz, np.identity(neigh.multH))
        # Compute the mod square of the inner product
        fx = abs(final.conjugate() @ bigSx @ initial) ** 2
        fy = abs(final.conjugate() @ bigSy @ initial) ** 2
        fz = abs(final.conjugate() @ bigSz @ initial) ** 2
        return fx, fy, fz

############################
    
    def plot_energies_brange(self, B_range, B_theta, B_phi):
        """ Plot all the energy levels of the system as a function of B field 
        strength. """
        plt.figure()
        plt.suptitle("Energy diagram as a function of B-field")
        plt.subplot(211)
        plt.plot(B_range, [self.energies('es', b, B_theta, B_phi) for b in B_range])
        plt.title("Excited state")
        plt.xlabel("B field / T")
        plt.ylabel("Energy / GHz")
        plt.subplot(212)
        plt.plot(B_range, [self.energies('gs', b, B_theta, B_phi) for b in B_range])
        plt.title("Ground state")
        plt.ylabel("Energy / GHz")

    def plot_optical_transitions(self, B_range, B_theta, B_phi):
        """ Plot all the optical transition energies as a function of B field. """
        plt.figure()
        # Take the 0-th component as the optical transitions function returns 
        # (transition_energy, initial_state, final_state) as a tuple.
        plt.plot(B_range, [[transition[0] for transition in self.optical_transitions(b, B_theta, B_phi)] for b in B_range])
        plt.title("Optical Transitions between energy levels")
        plt.xlabel("B field / T")
        plt.ylabel("Transition Energy / GHz")

    def plot_transitions_strengths(self, B_range, B_theta, B_phi, transition_type, axis=None):
        """ Plot all the optical transition energies as a function of B field. 
        The colour of the line represents the strength of that transition. """

        # Array in energy space (GHz) at which to compute the transition strength
        if transition_type == "optical":
            E_grid = np.arange(-10, 10, 0.001)
        else:
            E_grid = np.arange(0, 10, 0.001)
        E_grid_size = len(E_grid)
        B_grid_size = len(B_range)

        if axis is None:
            transition_grid_x = np.zeros((E_grid_size, B_grid_size))
            transition_grid_y = np.zeros((E_grid_size, B_grid_size))
            transition_grid_z = np.zeros((E_grid_size, B_grid_size))
        else:
            transition_grid = np.zeros((E_grid_size, B_grid_size))

        for B_idx, B in enumerate(B_range):
            # Update the B field and get the list of possible optical transitions
            # as a list of (transition_energy, (fx, fy, fy)) tuples where
            # fx, fy, fz refer to the transition strength for E field parallel
            # to each of the 3 axes.
            if transition_type == "optical":
                transitions = self.optical_transitions(B, B_theta, B_phi, compute_strengths=True)
            elif transition_type == "spin_gs":
                transitions = self.spin_transitions(B, B_theta, B_phi, compute_strengths=True)[0]
            elif transition_type == "spin_es":
                transitions = self.spin_transitions(B, B_theta, B_phi, compute_strengths=True)[1]
            else:
                raise Exception
            
            if axis is None:
                # Used to represent each column in the grid which we add each peak onto
                grid_col_x = np.zeros(E_grid_size)
                grid_col_y = np.zeros(E_grid_size)
                grid_col_z = np.zeros(E_grid_size)
            else:
                grid_col = np.zeros(E_grid_size)

            # For each possible optical transition at the particular value of 
            # B field, we take the transition energy (0-th comp) and create a 
            # Lorentzian peak around in the E_grid space, then scale it by its
            # amplitude given by transition[1] (x,y,z) comps.
            for transition in transitions:
                # FWHM of the Lorentzian
                fwhm = 0.1

                if axis is None:
                    grid_col_x += (fwhm/2)**2 * transition[1][0] / ( (E_grid - transition[0].real)**2 + (fwhm/2)**2 )
                    grid_col_y += (fwhm/2)**2 * transition[1][1] / ( (E_grid - transition[0].real)**2 + (fwhm/2)**2 )
                    grid_col_z += (fwhm/2)**2 * transition[1][2] / ( (E_grid - transition[0].real)**2 + (fwhm/2)**2 )
                else:
                    grid_col += (fwhm/2)**2 * transition[1][axis] / ( (E_grid - transition[0].real)**2 + (fwhm/2)**2 )
                
            if axis is None:
                # We reverse the direction of each row since imshow by default plots from top to bottom
                transition_grid_x[:, B_idx] = np.exp(-5 * grid_col_x[::-1])
                transition_grid_y[:, B_idx] = np.exp(-5 * grid_col_y[::-1])
                transition_grid_z[:, B_idx] = np.exp(-5 * grid_col_z[::-1])
            else:
                transition_grid[:, B_idx] = np.exp(-5 * grid_col[::-1])

        # Plot a slice of the intensity at a particular value of B field
        # plt.plot(E_grid, transition_grid[:, 0][::-1])

        if axis is None:
            plt.figure()
            plt.suptitle("{} Transitions between energy levels".format(transition_type.capitalize()))
            plt.subplot(131)
            plt.imshow(transition_grid_x, cmap="bone", extent=(B_range[0], B_range[-1], E_grid[0], E_grid[-1]), aspect='auto')
            plt.title("E field // x")
            plt.xlabel("B field / T")
            plt.ylabel("Transition Energy / GHz")

            plt.subplot(132)
            plt.imshow(transition_grid_y, cmap="bone", extent=(B_range[0], B_range[-1], E_grid[0], E_grid[-1]), aspect='auto')
            plt.title("E field // y")
            plt.xlabel("B field / T")

            plt.subplot(133)
            plt.imshow(transition_grid_z, cmap="bone", extent=(B_range[0], B_range[-1], E_grid[0], E_grid[-1]), aspect='auto')
            plt.title("E field // z")
            plt.xlabel("B field / T")
        else:
            plt.figure()
            plt.suptitle("{} Transitions between energy levels".format(transition_type))
            plt.imshow(transition_grid, cmap="bone", extent=(B_range[0], B_range[-1], E_grid[0], E_grid[-1]), aspect='auto')
            plt.title("E field // " + {0:"x", 1:"y", 2:"z"}[axis])
            plt.xlabel("B field / T")
            plt.ylabel("Transition Energy / GHz")

    def plot_optical_transitions_strengths_fixed_B(self, B, B_theta, B_phi, axis=None):
        """ Plot all the optical transition energies as a function of B field. 
        The colour of the line represents the strength of that transition. """

        # Array in energy space (GHz) at which to compute the transition strength
        E_grid = np.arange(-100, 100, 0.001)
        E_grid_size = len(E_grid)
        # FWHM of the Lorentzian
        fwhm = 0.001

        opt_trans = self.optical_transitions(B, B_theta, B_phi, compute_strengths=True)
        plt.figure()
        
        if axis is None:
            # Used to represent each column in the grid which we add each peak onto
            optical_peaks_x, optical_peaks_y, optical_peaks_z = np.zeros(E_grid_size), np.zeros(E_grid_size), np.zeros(E_grid_size)
        else:
            optical_peaks = np.zeros(E_grid_size)

        # For each possible optical transition at the particular value of 
        # B field, we take the transition energy (0-th comp) and create a 
        # Lorentzian peak around in the E_grid space, then scale it by its
        # amplitude given by transition[1] (x,y,z) comps.
        for idx, transition in enumerate(opt_trans):
            print("{}/{}".format(idx, len(opt_trans)))
            if axis is None:
                optical_peaks_x += (fwhm/2)**2 * transition[1][0] / ( (E_grid - transition[0].real)**2 + (fwhm/2)**2 )
                optical_peaks_y += (fwhm/2)**2 * transition[1][1] / ( (E_grid - transition[0].real)**2 + (fwhm/2)**2 )
                optical_peaks_z += (fwhm/2)**2 * transition[1][2] / ( (E_grid - transition[0].real)**2 + (fwhm/2)**2 )
            else:
                optical_peaks += (fwhm/2)**2 * transition[1][axis] / ( (E_grid - transition[0].real)**2 + (fwhm/2)**2 )

            # plt.annotate('Transition ({}, {})'.format(*transition[2]), xy=(transition[0], max(transition[1])))
            
        # Plot a slice of the intensity at a particular value of B field
        plt.title("Optical Transition Strengths with (B, B_theta, B_phi) = {0}".format((B, B_theta, B_phi)))
        if axis is None:
            plt.plot(E_grid, optical_peaks_x, '-', label="E // x")
            plt.plot(E_grid, optical_peaks_y, '--', label="E // y")
            plt.plot(E_grid, optical_peaks_z, '-.', label="E // z")

        else:
            plt.plot(E_grid, optical_peaks, label="E // " + {0:"x", 1:"y", 2:"z"}[axis])

        plt.xlabel("Transition Energy Detuning / GHz")
        plt.ylabel("Transition Strength")
        plt.legend()

    def plot_spin_transitions(self, B_range, B_theta, B_phi):
        """ Plot all the spin transition energies as a function of B field. """
        plt.figure()
        plt.suptitle("Spin Transitions within energy level")
        plt.subplot(211)
        plt.plot(B_range, np.array([[transition[0] for transition in self.spin_transitions(b, B_theta, B_phi)[1]] for b in B_range]))
        plt.title("Excited State Transitions")
        plt.xlabel("B field / T")
        plt.ylabel("Transition Energy / GHz")
        plt.subplot(212)
        plt.plot(B_range, np.array([[transition[0] for transition in self.spin_transitions(b, B_theta, B_phi)[0]] for b in B_range]))
        plt.title("Ground State Transitions")
        plt.xlabel("B field / T")
        plt.ylabel("Transition Energy / GHz")

    def plot_superhyperfine(self, B_range, B_theta, B_phi):
        """ Plot the superhyperfine splitted levels for the lowest energy levels
        (i.e. plot the lowest 2 energy levels after incorporating the SHF
        interaction). In addition, plot the energy gap between these SHF-split
        energy levels.
        """
        plt.figure()
        plt.suptitle("Superhyperfine splittings")

        ax1 = plt.subplot2grid((2, 2), (0, 0), colspan=1)
        ax1.plot(B_range, [self.superhyperfine_levels('gs', b, B_theta, B_phi)[:2] for b in B_range], c='C0')
        ax1.plot(B_range, [self.superhyperfine_levels('gs', b, B_theta, B_phi)[3:5] for b in B_range], c='C2')
        ax1.set_title("Relative Energies of ground superhyperfine doublet")
        ax1.set_xlabel("B field / T")
        ax1.set_ylabel("Relative Energy / kHz")

        ax2 = plt.subplot2grid((2, 2), (0, 1), colspan=1)
        ax2.plot(B_range, [self.superhyperfine_levels('es', b, B_theta, B_phi)[:2] for b in B_range], c='C1')
        ax2.plot(B_range, [self.superhyperfine_levels('es', b, B_theta, B_phi)[3:5] for b in B_range], c='C3')
        ax2.set_title("Relative Energies of excited superhyperfine doublet")
        ax2.set_xlabel("B field / T")
        ax2.set_ylabel("Relative Energy / kHz")

        ax3 = plt.subplot2grid((2, 2), (1, 0), colspan=2)
        ax3.plot(B_range, [self.superhyperfine_levels('gs', b, B_theta, B_phi)[2] for b in B_range], c='C0', label="Ground state Lower")
        ax3.plot(B_range, [self.superhyperfine_levels('gs', b, B_theta, B_phi)[5] for b in B_range], c='C2', label="Ground state Upper")
        ax3.plot(B_range, [self.superhyperfine_levels('es', b, B_theta, B_phi)[2] for b in B_range], c='C1', label="Excited state Lower")
        ax3.plot(B_range, [self.superhyperfine_levels('es', b, B_theta, B_phi)[5] for b in B_range], c='C3', label="Excited state Upper")
        ax3.set_title("Energy gap between the superhyperfine doublet levels")
        ax3.set_xlabel("B field / T")
        ax3.set_ylabel("Transition Energy / kHz")
        ax3.legend()
################################################################################

yb171_A_gs = np.array([[0.6745, 0,  0], #0.675, -4.82, from Ranon 1968, Kindem 2018
                       [0, 0.6745,   0],
                       [0, 0,  -4.8205]])


yb171_A_es = np.array([[3.39,   0,  0], # 3.37, 4.86, from Kindem 2018
                        [0, 3.39,  0],
                        [0,   0,  4.864]])

yb171_g_gs = np.array([[0.85, 0,  0], # From Ranon 1968
                       [0,  0.85,  0],
                       [0,  0, -6.08]])

yb171_g_es = np.array([[1.6, 0,  0], # 1.7, 2.51, from Kindem 2018
                       [0, 1.6,  0],
                       [0,  0, 2.51]])
                       
yb171_neighbours_list = [
        # Generated from VESTA for YVO structure from a Y site to other Y's or V's
        # Sorted by distance
        # Format: ((cartesian displacement vector in Angstrom), spin, nuclear_g, atom type)
        
        ((0.0, 0.0, -3.14465), 7/2, 1.4711, "V"), # 3.14465 
        # ((0.0, 0.0, 3.14465), 7/2, 1.4711, "V"),  # 3.14465

        # ((-3.55915, 0.0, 1.57232), 1/2, -0.2748308, "Y"), # 3.89098
        # ((3.55915, 0.0, 1.57232), 1/2, -0.2748308, "Y"), # 3.89098
        # ((0.0, -3.55915, -1.57232), 1/2, -0.2748308, "Y"), # 3.89098
        # ((0.0, 3.55915, -1.57232), 1/2, -0.2748308, "Y"), # 3.89098

        # (0.0, -3.55915, 1.57232), # V, 3.89098
        # (0.0, 3.55915, 1.57232), # V, 3.89098
        # (-3.55915, 0.0, -1.57232), # V, 3.89098
        # (3.55915, 0.0, -1.57232), # V, 3.89098

        # (-3.55915, -3.55915, 0.0), # V, 5.0334
        # (-3.55915, 3.55915, 0.0), # V, 5.0334
        # (3.55915, -3.55915, 0.0), # V, 5.0334
        # (3.55915, 3.55915, 0.0), # V, 5.0334

        # (-3.55915, 0.0, -4.71697), # Y, 5.90909
        # (3.55915, 0.0, -4.71697), # Y, 5.90909
        # (0.0, -3.55915, 4.71697), # Y, 5.90909
        # (0.0, 3.55915, 4.71697), # Y, 5.90909
        # (0.0, -3.55915, -4.71697), # V, 5.90909
        # (0.0, 3.55915, -4.71697), # V, 5.90909
        # (-3.55915, 0.0, 4.71697), # V, 5.90909
        # (3.55915, 0.0, 4.71697), # V, 5.90909
        ]                                   

yb171_electron_spin = 1/2
yb171_nuclear_spin = 1/2
yb171_g_nuclear = 0.98734

################################################################################

def rot(a, b, c):
    A = np.array([[np.cos(a), -np.sin(a), 0], [np.sin(a), np.cos(a), 0], [0, 0, 1]])
    B = np.array([[np.cos(b), 0, np.sin(b)], [0, 1, 0], [-np.sin(b), 0, np.cos(b)]])
    C = np.array([[np.cos(c), -np.sin(c), 0], [np.sin(c), np.cos(c), 0], [0, 0, 1]])
    return A @ B @ C

alpha = 144.9 / 180 * np.pi
beta = 34.9 / 180 * np.pi
gamma = 98.1 / 180 * np.pi
eu_g_gs = -rot(alpha, beta, gamma) @ np.diag([0.443, 0.5682, 1.1183]) @ rot(alpha, beta, gamma).T
eu_g_gs *= 10**7 # Convert from kHz/G to Hz/T
eu_g_gs *= (SpinSystem.h / SpinSystem.mu_b) # Convert from Hz/T to dimensionless
# Use this g matrix for electron spin to represent nuclear spin in Eu

eu_electron_spin = 5/2
eu_nuclear_spin = 0

# Use the hyperfine A matrix to represent the quadrupole Q matrix instead
# The original I.S interaction is replaced with S.S but actually represents I.I
alpha = -39.3 / 180 * np.pi
beta = 76.49 / 180 * np.pi
gamma = 149.9 / 180 * np.pi
eu_A_gs = rot(alpha, beta, gamma) @ np.diag([-2.735, 2.735, 12.3797]) @ rot(alpha, beta, gamma).T
eu_A_gs /= 1000 # Convert MHz -> GHz

eu_A_es = np.zeros((3, 3))
eu_g_nuclear = 0
eu_neighbours_list = []

# Used to toggle the interactions on/off
electron_zeeman = 1
hyperfine = 1
nuclear_zeeman_rei = 0



A = SpinSystem(
    eu_electron_spin,                                            # REI Electronic Spin
    eu_nuclear_spin,                        # REI Nuclear Spin
    electron_zeeman * eu_g_gs,                                   # REI Electronic GS g matrix
    electron_zeeman * eu_g_gs,                                   # REI ELectronic ES g matrix
    hyperfine * eu_A_gs,                                         # GS Hyperfine A matrix
    hyperfine * eu_A_es,                                         # ES Hyperfine A matrix
    nuclear_zeeman_rei * eu_g_nuclear,                           # REI Nuclear g coeff
    eu_neighbours_list
    )

# {1.93192, 1.80589, -0.34195}
A.plot_spin_transitions(np.arange(0, 3, 0.01), 1.80589, -0.34195)
plt.show()
################################################################################